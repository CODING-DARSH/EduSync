# parts of ml_model.py (updated queries)
import os
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib
import numpy as np
from db import execute_query

MODEL_PATH = os.path.join(os.getcwd(), 'models', 'risk_model.pkl')
os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

PASS_THRESHOLD = 40.0  # percent

def fetch_training_data():
    students = execute_query("SELECT id FROM Students", fetch=True)
    X = []
    y = []
    for (sid,) in students:
        rows = execute_query("SELECT COALESCE(marks,0) FROM StudentCourses WHERE student_id=%s", (sid,), fetch=True)
        if not rows:
            continue
        marks = [float(r[0]) for r in rows]
        avg_marks = float(sum(marks))/len(marks) if marks else 0.0

        att = execute_query("""
            SELECT AVG(present)::float * 100
            FROM Attendance a
            JOIN StudentCourses sc ON a.student_id=sc.student_id AND a.course_id=sc.course_id
            WHERE a.student_id=%s AND a.date_marked >= (CURRENT_DATE - INTERVAL '180 days')
        """, (sid,), fetch=True)
        avg_attendance = float(att[0][0] or 0.0)

        label = 1 if avg_marks >= PASS_THRESHOLD else 0
        X.append([avg_marks, avg_attendance])
        y.append(label)
    return np.array(X), np.array(y)

def train_and_save_model():
    X, y = fetch_training_data()
    if X.shape[0] < 10:
        print("Not enough training rows (need >=10). Model not trained.")
        return None
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', LogisticRegression(max_iter=1000))
    ])
    pipeline.fit(X, y)
    joblib.dump(pipeline, MODEL_PATH)
    print("✅ Model trained & saved to", MODEL_PATH)
    return pipeline

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

def predict_student_risk(student_id, model=None):
    if model is None:
        model = load_model()
    if model is None:
        return None

    rows = execute_query("SELECT COALESCE(marks,0) FROM StudentCourses WHERE student_id=%s", (student_id,), fetch=True)
    if not rows:
        avg_marks = 0.0
    else:
        marks = [float(r[0]) for r in rows]
        avg_marks = float(sum(marks))/len(marks) if marks else 0.0

    att = execute_query("""
        SELECT AVG(present)::float * 100
        FROM Attendance a
        WHERE a.student_id=%s AND a.date_marked >= (CURRENT_DATE - INTERVAL '180 days')
    """, (student_id,), fetch=True)
    avg_attendance = float(att[0][0] or 0.0)

    X = [[avg_marks, avg_attendance]]
    pass_prob = model.predict_proba(X)[0][1]
    risk_score = 1 - pass_prob
    label = 'low'
    if risk_score >= 0.75:
        label = 'high'
    elif risk_score >= 0.5:
        label = 'medium'
    return {'student_id': student_id, 'risk_score': risk_score, 'risk_label': label, 'avg_marks': avg_marks, 'avg_attendance': avg_attendance}

def predict_all_students(threshold=0.6):
    model = load_model()
    if model is None:
        m = train_and_save_model()
        if m is None:
            return []
        model = m

    students = execute_query("SELECT id FROM Students", fetch=True)
    results = []
    for (sid,) in students:
        r = predict_student_risk(sid, model)
        if r is None:
            continue
        # insert into StudentRisk and get generated id
        insert_q = """
            INSERT INTO StudentRisk (student_id, risk_score, risk_label, evaluated_at)
            VALUES (%s, %s, %s, NOW()) RETURNING id
        """
        new_id = execute_query(insert_q, (sid, float(r['risk_score']), r['risk_label']), fetch=False, returning=True)
        results.append(r)
        if r['risk_score'] >= threshold:
            # create notification
            execute_query(
                "INSERT INTO Notifications (student_id, message, created_at) VALUES (%s, %s, NOW())",
                (sid, f"⚠️ Risk warning: Your projected risk score is {r['risk_score']:.2f} ({r['risk_label']}). Please contact your teacher.")
            )
    return results
