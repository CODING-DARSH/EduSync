import os
import joblib
import numpy as np
from datetime import datetime, timedelta, date
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from db import execute_query
from models import send_email, send_sms, send_notification_contacts_for_student

MODEL_DIR = os.path.join(os.getcwd(), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "risk_model.pkl")
os.makedirs(MODEL_DIR, exist_ok=True)

MIN_TRAIN_ROWS = 10
LOOKBACK_DAYS = 90                   # <-- changed to 90 days
ATTENDANCE_THRESHOLD = 60.0          # percent
MARK_THRESHOLD = 40.0                # marks threshold
MIN_SUBJECTS = 6
RISK_SCORE_THRESHOLD = 0.6

# ---------------- helper DB fetchers ----------------
def _fetch_students():
    rows = execute_query("SELECT id, name, email, parent_email FROM Students", fetch=True)
    return rows or []

def _get_student_marks(student_id):
    rows = execute_query("SELECT COALESCE(marks, 0) FROM StudentCourses WHERE student_id=%s", (student_id,), fetch=True)
    if not rows:
        return []
    return [float(r[0]) for r in rows]

def _get_student_attendance_percent(student_id, lookback_days=LOOKBACK_DAYS):
    """
    Compute attendance percent over the past `lookback_days` using a Python computed cutoff date.
    Returns a float 0..100
    """
    cutoff = date.today() - timedelta(days=int(lookback_days))
    q = """
        SELECT COALESCE(AVG(present)::float, 0) * 100
        FROM Attendance a
        WHERE a.student_id=%s AND a.date_marked >= %s
    """
    data = execute_query(q, (student_id, cutoff), fetch=True)
    if not data:
        return 0.0
    return float(data[0][0] or 0.0)

# ---------------- feature / label builders ----------------
def _feature_vector_for_student(student_id):
    marks = _get_student_marks(student_id)
    if marks:
        avg_marks = float(sum(marks) / len(marks))
    else:
        avg_marks = 0.0

    attendance_pct = _get_student_attendance_percent(student_id)
    below_count = sum(1 for m in marks if m < MARK_THRESHOLD)

    # pad if fewer than MIN_SUBJECTS so features are consistent
    if len(marks) < MIN_SUBJECTS:
        pad = [0.0] * (MIN_SUBJECTS - len(marks))
        marks_padded = marks + pad
        avg_marks = float(sum(marks_padded) / MIN_SUBJECTS)
        below_count = sum(1 for m in marks_padded if m < MARK_THRESHOLD)

    return [avg_marks, attendance_pct, below_count]

def _label_from_rules(avg_marks, attendance_pct, below_count):
    # deterministic rule for "at-risk" used to bootstrap training labels
    if attendance_pct < ATTENDANCE_THRESHOLD or below_count >= 3:
        return 1
    return 0

# ---------------- dataset builders ----------------
def _build_training_dataset():
    X = []
    y = []
    students = _fetch_students()
    for sid, *_ in students:
        marks = _get_student_marks(sid)
        attendance = _get_student_attendance_percent(sid)
        below_count = sum(1 for m in marks if m < MARK_THRESHOLD)
        if marks:
            avg_marks = float(sum(marks) / len(marks))
        else:
            avg_marks = 0.0

        if len(marks) < MIN_SUBJECTS:
            pad = [0.0] * (MIN_SUBJECTS - len(marks))
            marks_padded = marks + pad
            avg_marks = float(sum(marks_padded) / MIN_SUBJECTS)
            below_count = sum(1 for m in marks_padded if m < MARK_THRESHOLD)

        X.append([avg_marks, attendance, below_count])
        y.append(_label_from_rules(avg_marks, attendance, below_count))

    X = np.array(X) if X else np.empty((0, 3))
    y = np.array(y) if y else np.empty((0,))
    return X, y

def _generate_synthetic_data(n_needed):
    rng = np.random.RandomState(42)
    X = []
    y = []
    for _ in range(n_needed):
        avg_marks = float(rng.normal(55, 25))
        avg_marks = max(0.0, min(100.0, avg_marks))
        attendance = float(rng.normal(70, 25))
        attendance = max(0.0, min(100.0, attendance))
        below = int(np.clip(int(rng.poisson(1.5)), 0, MIN_SUBJECTS))
        label = _label_from_rules(avg_marks, attendance, below)
        X.append([avg_marks, attendance, below])
        y.append(label)
    return np.array(X), np.array(y)

# ---------------- training / model persistence ----------------
def train_and_save_model(force_retrain=False):
    X, y = _build_training_dataset()

    # bootstrap with synthetic if too few rows
    if X.shape[0] < MIN_TRAIN_ROWS:
        need = MIN_TRAIN_ROWS - X.shape[0]
        if need > 0:
            Xs, ys = _generate_synthetic_data(need)
            if X.shape[0] == 0:
                X, y = Xs, ys
            else:
                X = np.vstack([X, Xs])
                y = np.concatenate([y, ys])

    if X.shape[0] < MIN_TRAIN_ROWS:
        print("Not enough data to train even after synthetic augmentation.")
        return None

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000))
    ])
    pipeline.fit(X, y)
    joblib.dump(pipeline, MODEL_PATH)
    print("✅ Model trained & saved to", MODEL_PATH)
    return pipeline

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return None

# ---------------- prediction ----------------
def predict_student_risk(student_id, model=None):
    features = _feature_vector_for_student(student_id)
    avg_marks, attendance_pct, below_count = features
    rule_label = _label_from_rules(avg_marks, attendance_pct, below_count)

    if model is None:
        model = load_model()

    if model is None:
        # fallback to rule-only
        risk_score = 1.0 if rule_label == 1 else 0.0
    else:
        try:
            proba = model.predict_proba([features])[0]
            # determine index of class=1
            if hasattr(model, "classes_") and 1 in list(model.classes_):
                idx1 = list(model.classes_).index(1)
                prob_risk = proba[idx1]
            else:
                prob_risk = proba[-1]
            risk_score = float(prob_risk)
        except Exception:
            risk_score = 1.0 if rule_label == 1 else 0.0

    # Boost score if rule indicates risk
    if rule_label == 1 and risk_score < 0.75:
        risk_score = max(risk_score, 0.75)

    if risk_score >= 0.75:
        risk_label = "high"
    elif risk_score >= 0.5:
        risk_label = "medium"
    else:
        risk_label = "low"

    return {
        "student_id": student_id,
        "avg_marks": avg_marks,
        "attendance_pct": attendance_pct,
        "below_count": below_count,
        "risk_score": float(risk_score),
        "risk_label": risk_label
    }

def predict_all_students(threshold=RISK_SCORE_THRESHOLD, notify=True):
    model = load_model()
    if model is None:
        model = train_and_save_model()
        if model is None:
            print("Model unavailable and training failed.")
            return []

    students = _fetch_students()
    results = []

    for sid, sname, semail, parent_email in students:

        r = predict_student_risk(sid, model)

        # Insert into StudentRisk table
        try:
            insert_q = """
                INSERT INTO StudentRisk (student_id, risk_score, risk_label, evaluated_at)
                VALUES (%s, %s, %s, NOW())
            """
            execute_query(insert_q, (sid, float(r['risk_score']), r['risk_label']))
        except Exception as e:
            print("StudentRisk insert error:", e)

        results.append({"id": sid, "name": sname, **r})

        # ----------------------- ONE-TIME NOTIFICATION LOGIC -----------------------
        if notify and r["risk_score"] >= threshold:
            try:
                row = execute_query(
                    "SELECT notified FROM StudentRisk WHERE student_id=%s ORDER BY id DESC LIMIT 1",
                    (sid,), fetch=True
                )

                already_notified = row and row[0][0] is True

                if not already_notified:
                    msg = f"""
Dear {sname},

Our system detected that your academic risk score is {r['risk_score']:.2f}, which places you in the **{r['risk_label'].upper()} RISK** category.

📊 Performance Summary:
• Average Marks: {r['avg_marks']}
• Attendance (last 90 days): {r['attendance_pct']}%
• Low-Scoring Subjects (<40 marks): {r['below_count']}

This means you may require additional attention in academics or attendance.
Please reach out to your teacher or academic advisor for support.

Regards,
EduSync Portal
"""



                    # save notification
                    execute_query(
                        "INSERT INTO Notifications (student_id, message, created_at) VALUES (%s, %s, NOW())",
                        (sid, msg)
                    )

                    # send to student + parent
                    if semail:
                        send_email(semail, "Risk alert from Student Portal", msg)
                    if parent_email:
                        send_email(parent_email, "Risk alert for your child", msg)

                    # update flag
                    execute_query(
                        "UPDATE StudentRisk SET notified=TRUE WHERE student_id=%s ORDER BY id DESC LIMIT 1",
                        (sid,)
                    )

            except Exception as e:
                print("Notification error:", e)
        # --------------------------------------------------------------------------

    return results
