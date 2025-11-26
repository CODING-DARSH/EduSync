# app.py
from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory, url_for, flash
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ml_model import predict_all_students
from flask import Flask, render_template, request, redirect, session, jsonify
from ml_model import predict_all_students, predict_student_risk, train_and_save_model, load_model
from models import Teacher, TeacherPost, Notification, AttendanceModel, send_email, send_notification_contacts_for_student
from db import execute_query
import json
from flask import Blueprint, render_template, request, jsonify, session
from db import execute_query
from datetime import datetime


from models import (
    Student,
    Teacher,
    Admin,
    OTP,
    send_email,
    send_sms,
    Assignment,
    Submission,
    Notification,
    TeacherNotification,
    AttendanceModel,
    TeacherPost
)

from db import execute_query
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret")
app.jinja_env.filters['zip'] = zip

# ---------------- UPLOAD FOLDER ----------------
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template('landing.html')
@app.route('/login')
def login_page():
    return render_template('login.html')
@app.route('/student/resend-otp', methods=['POST'])
def resend_otp():
    student_id = request.form.get('id')

    if not student_id:
        return "Missing student id", 400

    # generate new OTP (old ones auto-expire based on your new logic)
    otp = OTP.generate_otp(student_id)

    # fetch email
    row = execute_query("SELECT email FROM Students WHERE id=%s", (student_id,), fetch=True)
    if row and row[0][0]:
        send_email(row[0][0], "Your Login OTP", f"Your new OTP is {otp}")

    return render_template("student_verify_otp.html",
                           student_id=student_id,
                           message="✅ New OTP sent!")


# ---------------- STUDENT UPLOAD ----------------
@app.route('/student/upload', methods=['POST'])
def student_upload():
    if 'student_id' not in session:
        return redirect('/')

    file = request.files.get('file')
    assignment_id = request.form.get('assignment_id')
    student_id = session['student_id']

    if not assignment_id:
        flash("Assignment ID missing.", "error")
        return redirect(url_for('student_dashboard'))

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        Submission.submit(assignment_id, student_id, filename)
        flash("✅ Assignment uploaded successfully.", "success")
    else:
        flash("❌ No file selected.", "error")

    return redirect(url_for('student_dashboard'))

# ---------------- STUDENT REGISTER ----------------
@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        internal_id, student_code = Student.register(
            request.form['name'],
            request.form['email'],
            request.form['phone'],
            request.form['password']
        )
        return render_template(
            "student_register_success.html",
            student_id=internal_id,
            student_code=student_code
        )
    return render_template('register.html')


# ---------------- STUDENT LOGIN ----------------
@app.route('/student/login', methods=['POST'])
def student_login():
    student_code = request.form['id']      # now this field is EDU00001 style
    password = request.form['password']
    user = Student.login(student_code, password)
    if user:
        # user[0] = internal numeric id
        session['student_id'] = user[0]
        return redirect('/student/dashboard')
    return redirect("/login?error=student")    

# ---------------- STUDENT REQUEST OTP ----------------
@app.route('/student/request-otp', methods=['POST'])
def request_otp():
    student_code = request.form.get('id')
    form_email = request.form.get('email')
    form_phone = request.form.get('phone')

    if not student_code:
        return "Missing student id", 400

    # 🔁 Map code -> internal numeric id
    row = execute_query(
        "SELECT id,name,email, phone FROM Students WHERE student_code=%s",
        (student_code,),
        fetch=True
    )
    if not row:
        return "Student not found", 404

    student_id,student_name, db_email, db_phone = row[0]

    otp = OTP.generate_otp(student_id)

    try:
        if form_email:
            msg = f"""
<p>This message concerns your EduSync account, <strong>{student_name}</strong>.</p>

<p>Your one-time authentication code is:<br>
<b style="font-size:20px;">{otp}</b></p>

<p>This code will expire in <b>1 minute</b> and can only be used once.</p>

<p>If you did not initiate this request, no action is required.</p>

<p>Regards,<br>
EduSync Security Team</p>
"""


            send_email(form_email, "EduSync Login Verification", msg)


        elif form_phone:
            send_sms(form_phone, f"Your OTP is {otp}")

        else:
            # fallback to DB email/phone
            email, phone = db_email, db_phone
            if email:
                send_email(email, "Your Login OTP", f"Your OTP is {otp}")
            elif phone:
                send_sms(phone, f"Your OTP is {otp}")
            else:
                return "No contact found", 400
    except Exception as e:
        print("OTP send error:", e)
        return "Failed to send OTP", 500

    return render_template(
        "student_verify_otp.html",
        student_code=student_code,
        message="OTP sent successfully!"
    )


# ---------------- VERIFY OTP ----------------
@app.route('/student/verify-otp', methods=['POST'])
def verify_otp():
    student_code = request.form['id']
    otp_code = request.form['otp']
    print("FORM DATA =>", request.form)
    # Map code back to internal id
    row = execute_query(
        "SELECT id FROM Students WHERE student_code=%s",
        (student_code,),
        fetch=True
    )
    if not row:
        return "Invalid Student ID."

    student_id = row[0][0]

    if OTP.verify_otp(student_id, otp_code):
        session['student_id'] = student_id
        return redirect('/student/dashboard')
    else:
        return "Invalid or expired OTP."

@app.route('/student/forgot-password', methods=['GET', 'POST'])
def student_forgot_password():
    if request.method == 'GET':
        return render_template('student_forgot_password.html')

    # POST: user submitted form
    student_code = request.form.get('student_code')
    email = request.form.get('email')

    if not student_code or not email:
        return "Student ID and email are required.", 400

    # find student
    row = execute_query(
        "SELECT id,name,email FROM Students WHERE student_code=%s",
        (student_code,),
        fetch=True
    )

    if not row:
        return "Student not found.", 404

    student_id,student_name,db_email = row[0]

    if db_email is None or db_email.strip().lower() != email.strip().lower():
        return "Email does not match our records.", 400

    # generate OTP & send email
    otp = OTP.generate_otp(student_id)
    try:
        msg = f"""
            <p>A password reset was requested for your EduSync account, <strong>{student_name}</strong>.</p>

            <p>
            Your verification code is:<br>
            <b style="font-size:20px;">{otp}</b>
            </p>

            <p>
            This code expires in <b>1 minutes</b> and can only be used once.
            </p>

            <p>
            If you did not request this, no action is required.
            </p>

            <p>— EduSync Security Team</p>
        """
        send_email(email, "Reset Your EduSync Password", msg)

    except Exception as e:
        print("Password reset OTP send error:", e)
        return "Failed to send OTP.", 500

    # store which student we're resetting in a safe way
    session['reset_student_id'] = student_id

    return render_template(
        'student_reset_verify_otp.html',
        student_code=student_code,
        email=email
    )
@app.route('/student/forgot-password/verify', methods=['POST'])
def student_forgot_password_verify():
    otp_code = request.form.get('otp')
    student_id = session.get('reset_student_id')

    if not student_id:
        return "Session expired. Please start the password reset again.", 400

    if not otp_code:
        return "OTP is required.", 400

    if OTP.verify_otp(student_id, otp_code):
        # OTP verified – show reset-password form
        return render_template('student_reset_password.html')
    else:
        return "Invalid or expired OTP.", 400
@app.route('/student/forgot-password/reset', methods=['POST'])
def student_forgot_password_reset():
    from models import Student  # if not already imported at top

    student_id = session.get('reset_student_id')
    if not student_id:
        return "Session expired. Please start the reset process again.", 400

    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or not confirm_password:
        return "Both password fields are required.", 400

    if new_password != confirm_password:
        return "Passwords do not match.", 400

    # ✅ UPDATE PASSWORD IN DB
    Student.reset_password(student_id, new_password)

    # clear reset session
    session.pop('reset_student_id', None)

    # you can flash a message if you want, but simplest:
    return render_template('student_reset_success.html')

# ---------------- STUDENT DASHBOARD ----------------
@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect('/')

    sid = session['student_id']
    student = Student.get_details(sid)
    courses = Student.show_courses(sid)

    assignments = execute_query("""
        SELECT 
            a.id, a.title, a.due_date,
            s.file_path, s.marks
        FROM Assignments a
        JOIN StudentCourses sc ON a.course_id = sc.course_id
        LEFT JOIN Submissions s ON s.assignment_id = a.id AND s.student_id = %s
        WHERE sc.student_id = %s
        ORDER BY a.due_date
    """, (sid, sid), fetch=True)

    grades = Student.get_course_grades(sid)
    labels = [g[0] for g in grades]
    values = [float(g[1]) for g in grades]

    notifications = Notification.get_for_student(sid)

    return render_template("student_dashboard.html",
                           student=student,
                           courses=courses,
                           assignments=assignments,
                           notifications=notifications,
                           chart_labels=labels,
                           chart_data=values)

# ---------------- STUDENT PROFILE ----------------
@app.route('/student/profile')
def student_profile():
    if 'student_id' not in session:
        return redirect('/')
    return render_template('student_profile.html', student=Student.get_details(session['student_id']))

# ---------------- UPDATE PASSWORD ----------------
@app.route('/student/update_password', methods=['POST'])
def update_password():
    if 'student_id' not in session:
        return redirect('/')
    Student.change_password(session['student_id'], request.form['old_password'], request.form['new_password'])
    return redirect('/student/profile')

# ---------------- EXPORT CSV ----------------
@app.route('/student/export')
def student_export():
    Student.export_csv(session['student_id'])
    return "Your report has been downloaded successfully!"

# ---------------- STUDENT NOTIFICATIONS ----------------
@app.route('/student/notifications')
def student_notifications():
    if 'student_id' not in session:
        return redirect('/')
    return render_template('student_notifications.html', notifications=Student.get_notifications(session['student_id']))

# ---------------- STUDENT SUBMISSIONS ----------------
@app.route('/student/submissions')
def student_submissions():
    if 'student_id' not in session:
        return redirect('/')
    return render_template('student_submissions.html', submissions=Submission.get_for_student(session['student_id']))

# ---------------- ENROLL COURSE ----------------
@app.route('/student/enroll', methods=['POST'])
def enroll():
    if 'student_id' not in session:
        return redirect('/')
    Student.enroll(session['student_id'], request.form['course_id'])
    return redirect('/student/dashboard')

# ---------------- LOGOUT ----------------
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/')

# ---------------- TEACHER LOGIN ----------------
@app.route('/teacher/login', methods=['POST'])
def teacher_login():
    user = Teacher.login(request.form['id'], request.form['password'])
    if user:
        session['teacher_id'] = user[0]
        return redirect('/teacher/dashboard')
    return redirect("/login?error=teacher")


# ---------------- TEACHER REGISTER ----------------
@app.route('/teacher/register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        teacher_id = Teacher.register(request.form['name'], request.form['password'])
        return f"Registered! Your Teacher ID is {teacher_id}. <a href='/'>Login</a>"
    return render_template('teacher_register.html')

 # <-- ADD THIS AT TOP OF FILE

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect('/')
    tid = session['teacher_id']
    teacher_row = execute_query("SELECT id, name FROM Teachers WHERE id=%s", (tid,), fetch=True)
    teacher = teacher_row[0] if teacher_row else None

    # The students query you already had
    students = execute_query("""
        SELECT s.id, s.name, c.course_name, c.id
        FROM Students s
        JOIN StudentCourses sc ON s.id = sc.student_id
        JOIN Courses c ON sc.course_id = c.id
        JOIN TeacherCourses tc ON c.id = tc.course_id
        WHERE tc.teacher_id = %s
    """, (tid,), fetch=True)
    events = execute_query("""
    SELECT title, event_date 
    FROM TeacherCalendar
    WHERE teacher_id = %s
    ORDER BY event_date ASC
    """, (tid,), fetch=True)



    courses = Teacher.get_courses(tid)
    assignments = execute_query("SELECT id, title, due_date FROM Assignments WHERE teacher_id=%s ORDER BY due_date DESC", (tid,), fetch=True)
    posts = TeacherPost.get_for_teacher(tid)
    notifications = TeacherNotification.get_for_teacher(tid)  # or TeacherNotification.get_for_teacher

    # Attendance summary (existing code)
    attendance_summary = []
    for cid, cname in courses or []:
        data = execute_query("""
            SELECT s.name, ROUND(AVG(a.present)*100,2)
            FROM Attendance a
            JOIN Students s ON a.student_id = s.id
            WHERE a.course_id = %s
            GROUP BY s.name
            ORDER BY s.name
        """, (cid,), fetch=True)
        attendance_summary.append({
            'course_id': cid, 'course_name': cname,
            'records': [{'name': r[0], 'percent': float(r[1] or 0)} for r in data or []]
        })

    # ML predictions: get cached model predictions, do not send email here
    try:
        preds = predict_all_students(threshold=0.6, notify=False)  # returns list
        at_risk = [p for p in preds if p['risk_label'] in ('high', 'medium')]
    except Exception as e:
        print("ML ERROR:", e)
        preds = []
        at_risk = []

    return render_template('teacher_dashboard.html',
                           teacher=teacher,
                           students=students,
                           courses=courses,
                           assignments=assignments,
                           posts=posts,
                           notifications=notifications,
                           attendance_summary=attendance_summary,
                            events=events,
                           at_risk_list=at_risk)
@app.route('/teacher/risk/reset_flags', methods=['POST'])
def reset_risk_flags():
    execute_query("UPDATE StudentRisk SET notified=FALSE")
    return jsonify({"message": "All notification flags have been reset"})

from ml_model import predict_all_students

@app.route('/api/risk/scan')
def api_risk_scan():
    results = predict_all_students(notify=False)   # DO NOT send emails
    return jsonify(results)
@app.route('/api/risk/send', methods=['POST'])
def api_risk_send():
    data = request.json
    student_ids = data.get("students", [])

    sent = 0
    errs = []

    for sid in student_ids:

        # fetch latest risk entry
        row = execute_query("""
            SELECT s.email, s.parent_email, sr.id, s.name, sr.risk_score, sr.risk_label
            FROM Students s
            JOIN StudentRisk sr ON s.id = sr.student_id
            WHERE s.id = %s
            ORDER BY sr.id DESC
            LIMIT 1
        """, (sid,), fetch=True)

        if not row:
            continue

        email, parent, risk_id, sname, risk_score, risk_label = row[0]

        # fetch more ML features
        avg_marks = execute_query("SELECT COALESCE(AVG(marks),0) FROM StudentCourses WHERE student_id=%s", (sid,), fetch=True)[0][0]
        attendance = execute_query("""
            SELECT COALESCE(AVG(present)::float*100,0)
            FROM Attendance
            WHERE student_id=%s AND date_marked >= NOW() - interval '90 days'
        """, (sid,), fetch=True)[0][0]
        below_count = execute_query("""
            SELECT COUNT(*) FROM StudentCourses WHERE student_id=%s AND marks < 40
        """, (sid,), fetch=True)[0][0]

        try:
            msg = f"""
Dear {sname},

Our system detected that your academic risk score is {risk_score:.2f}, which places you in the **{risk_label.upper()} RISK** category.

📊 Performance Summary:
• Average Marks: {avg_marks:.2f}
• Attendance (last 90 days): {attendance:.2f}%
• Low-Scoring Subjects (<40 marks): {below_count}

This means you may require additional attention in academics or attendance.
Please reach out to your teacher or academic advisor for support.

Regards,
EduSync Portal
"""

            if email:
                send_email(email, "Academic Risk Alert", msg)

            if parent:
                send_email(parent, "Risk Alert for Your Child", msg)

            execute_query("UPDATE StudentRisk SET notified=TRUE WHERE id=%s", (risk_id,))

            sent += 1

        except Exception as e:
            errs.append(str(e))

    return jsonify({"sent": sent, "errors": errs})

# Returns analytics summary for charts
@app.route('/api/analytics')
def api_analytics():
    # Simple aggregated analytics for frontend charts
    # avg attendance across all courses (lookback 90 days)
    rows = execute_query("""
        SELECT AVG(t.avg_att) FROM (
          SELECT ROUND(AVG(a.present)*100,2) as avg_att
          FROM Attendance a
          GROUP BY a.student_id
        ) t
    """, fetch=True)
    avg_att = float(rows[0][0]) if rows and rows[0][0] is not None else 0.0

    # avg marks across StudentCourses
    rows2 = execute_query("SELECT AVG(marks) FROM StudentCourses WHERE marks IS NOT NULL", fetch=True)
    avg_marks = float(rows2[0][0]) if rows2 and rows2[0][0] is not None else 0.0

    # simple timeseries placeholder -> return past 7 days labels
    import datetime
    labels = []
    attendance_series = []
    marks_series = []
    at_risk_series = []
    for d in range(6, -1, -1):
        day = (datetime.date.today() - datetime.timedelta(days=d)).strftime('%b %d')
        labels.append(day)
        attendance_series.append(round(avg_att * (0.9 + 0.2 * (d/6)), 2))  # synthetic for display
        marks_series.append(round(avg_marks * (0.95 + 0.1 * (d/6)), 2))
        at_risk_series.append( int(max(0, 2 - d/3)) )  # synthetic

    # at-risk count
    preds = predict_all_students(threshold=0.6, notify=False)
    at_risk_count = len([p for p in preds if p['risk_label'] in ('high','medium')])

    return jsonify({
        "avg_attendance": avg_att,
        "avg_marks": avg_marks,
        "labels": labels,
        "attendance_series": attendance_series,
        "marks_series": marks_series,
        "at_risk_series": at_risk_series,
        "at_risk_count": at_risk_count
    })
@app.route("/teacher/course/<int:course_id>/marks")
def teacher_course_marks(course_id):
    if "teacher_id" not in session:
        return redirect("/")

    tid = session["teacher_id"]

    # Check teacher teaches the course
    check = execute_query("""
        SELECT 1 FROM TeacherCourses WHERE teacher_id=%s AND course_id=%s
    """, (tid, course_id), fetch=True)

    if not check:
        return "Unauthorized", 403

    students = execute_query("""
        SELECT s.id, s.name, sc.marks
        FROM Students s
        JOIN StudentCourses sc ON s.id=sc.student_id
        WHERE sc.course_id=%s
        ORDER BY s.name
    """, (course_id,), fetch=True)

    course = execute_query("SELECT course_name FROM Courses WHERE id=%s",
                           (course_id,), fetch=True)

    return render_template("teacher_course_marks.html",
                           rows=students,
                           course_id=course_id,
                           course_name=course[0][0] if course else "Course")
@app.route("/teacher/course/<int:course_id>/marks/update", methods=["POST"])
def teacher_update_marks(course_id):

    # 1) Try JSON first (existing logic)
    data = request.get_json(silent=True)

    if data and "updates" in data:
        updates = data["updates"]
        for entry in updates:
            sid = entry["student_id"]
            marks = entry["marks"]
            execute_query("""
                UPDATE StudentCourses
                SET marks=%s
                WHERE student_id=%s AND course_id=%s
            """, (marks, sid, course_id))
        return jsonify({"status": "success"})

    # 2) Handle normal HTML form POST (your actual use case)
    for key, value in request.form.items():
        if key.startswith("marks_"):
            sid = key.split("_")[1]
            marks = value if value != "" else None
            execute_query("""
                UPDATE StudentCourses
                SET marks=%s
                WHERE student_id=%s AND course_id=%s
            """, (marks, sid, course_id))

    return redirect(f"/teacher/course/{course_id}/marks?saved=1")


# Activity feed
@app.route('/api/activity_recent')
def api_activity_recent():
    rows = execute_query("SELECT message, to_char(created_at,'YYYY-MM-DD HH24:MI') FROM TeacherPosts ORDER BY created_at DESC LIMIT 8", fetch=True)
    data = [{"message": r[0], "when": r[1]} for r in rows] if rows else []
    return jsonify(data)

# Attendance heatmap data per course
@app.route('/api/attendance_heatmap')
def api_attendance_heatmap():
    course_id = request.args.get('course_id')
    if not course_id:
        return jsonify({"error":"course_id required"}), 400

    # Return simplified heatmap: list of { student_id, name, daily: [ {date, present} ... ] }
    # We'll limit to last 30 days for payload sizings
    rows = execute_query("""
        SELECT s.id, s.name
        FROM Students s
        JOIN StudentCourses sc ON s.id=sc.student_id
        WHERE sc.course_id=%s
        ORDER BY s.name
    """, (course_id,), fetch=True)
    students = rows or []

    import datetime
    start = datetime.date.today() - datetime.timedelta(days=29)
    dates = [(start + datetime.timedelta(days=i)).isoformat() for i in range(30)]

    payload = []
    for sid, name in students:
        q = """
          SELECT DATE(date_marked), present
          FROM Attendance
          WHERE student_id=%s AND course_id=%s AND date_marked >= %s
        """
        rows2 = execute_query(q, (sid, course_id, start), fetch=True)
        present_map = { str(r[0]): int(r[1]) for r in (rows2 or []) }
        daily = [ present_map.get(d, 0) for d in dates ]
        payload.append({"student_id": sid, "name": name, "daily": daily})
    return jsonify({"dates": dates, "students": payload})

# Predict single student (returns feature + risk)
@app.route('/api/predict_student/<int:student_id>')
def api_predict_student(student_id):
    try:
        r = predict_student_risk(student_id, None)
        return jsonify(r)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Predict all students (optionally notify)
@app.route('/api/predict_all')
def api_predict_all():
    notify = request.args.get('notify', 'false').lower() == 'true'
    try:
        preds = predict_all_students(threshold=0.6, notify=notify)
        return jsonify(preds)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# POST route to send one-time risk notifications to currently at-risk students
@app.route('/teacher/risk/notify', methods=['POST'])
def teacher_risk_notify():
    if 'teacher_id' not in session:
        return jsonify({"error":"not authorized"}), 401
    try:
        preds = predict_all_students(threshold=0.6, notify=False)
        # send only to those currently high or medium risk and not notified previously
        sent = 0
        for p in preds:
            sid = p['student_id']
            if p['risk_label'] not in ('high','medium'): 
                continue
            # check last StudentRisk notified flag (if exists)
            row = execute_query("SELECT notified FROM StudentRisk WHERE student_id=%s ORDER BY id DESC LIMIT 1", (sid,), fetch=True)
            already = bool(row and row[0][0])
            if already:
                continue
            # make message
            msg = f"⚠️ Risk alert: Your risk score is {p['risk_score']:.2f} ({p['risk_label']}). Avg marks: {p['avg_marks']:.1f}. Attendance: {p['attendance_pct']:.1f}%."
            # create notification row
            execute_query("INSERT INTO Notifications (student_id, message, created_at) VALUES (%s, %s, NOW())", (sid, msg))
            # send email (models.send_email will print in dev mode if env not set)
            if p.get('email'):
                try:
                    send_email(p.get('email'), "Risk alert from EduSync", msg)
                except Exception as e:
                    print("send_email error", e)
            # update StudentRisk notified flag for the latest entry (safe UPDATE using subquery)
            try:
                execute_query("""
                    UPDATE StudentRisk SET notified=TRUE
                    WHERE id = (
                      SELECT id FROM StudentRisk WHERE student_id=%s ORDER BY id DESC LIMIT 1
                    )
                """, (sid,))
            except Exception as e:
                print("Failed to update StudentRisk notified flag:", e)
            sent += 1
        return jsonify({"message": f"Notifications sent: {sent}"})
    except Exception as e:
        print("teacher_risk_notify error:", e)
        return jsonify({"error": str(e)}), 500
calendar_bp = Blueprint('calendar', __name__)

# Render the full calendar page (teacher-only)
@calendar_bp.route('/teacher/calendar')
def teacher_calendar():
    if 'teacher_id' not in session:
        return redirect('/')
    tid = session['teacher_id']
    teacher = execute_query("SELECT id, name FROM Teachers WHERE id=%s", (tid,), fetch=True)
    teacher = teacher[0] if teacher else None
    # courses used in sidebar (if you want)
    courses = execute_query("""
        SELECT c.id, c.course_name
        FROM Courses c
        JOIN TeacherCourses tc ON c.id = tc.course_id
        WHERE tc.teacher_id = %s
    """, (tid,), fetch=True)
    return render_template('teacher_calendar.html', teacher=teacher, courses=courses or [])

# API: fetch events between start & end (FullCalendar sends ISO dates)
@calendar_bp.route('/api/calendar/events')
def api_calendar_events():
    if 'teacher_id' not in session:
        return jsonify([]), 401
    tid = session['teacher_id']
    start = request.args.get('start')  # ISO date/time
    end = request.args.get('end')
    try:
        # parse to guard format; DB will filter by timestamps
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except Exception:
        return jsonify({"error": "invalid start/end"}), 400

    q = """
      SELECT id, title, description, start_ts, end_ts, all_day, color
      FROM TeacherCalendar
      WHERE teacher_id=%s AND start_ts >= %s AND start_ts <= %s
      ORDER BY start_ts
    """
    rows = execute_query(q, (tid, s, e), fetch=True)
    events = []
    for r in rows or []:
        eid, title, desc, start_ts, end_ts, all_day, color = r
        events.append({
            "id": str(eid),
            "title": title,
            "start": start_ts.isoformat(),
            "end": end_ts.isoformat(),
            "allDay": bool(all_day),
            "color": color,
            "extendedProps": {"description": desc or ""}
        })
    return jsonify(events)

# API: create event
@calendar_bp.route('/api/calendar/event', methods=['POST'])
def api_calendar_create_event():
    if 'teacher_id' not in session:
        return jsonify({"error": "unauth"}), 401
    tid = session['teacher_id']
    body = request.get_json() or {}
    title = body.get('title') or 'Untitled'
    description = body.get('description') or ''
    start = body.get('start')
    end = body.get('end') or start
    all_day = bool(body.get('allDay', False))
    color = body.get('color', '#10b981')

    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except Exception:
        return jsonify({"error": "invalid datetime"}), 400

    q = """
        INSERT INTO TeacherCalendar (teacher_id, title, description, start_ts, end_ts, all_day, color, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()) RETURNING id
    """
    new_id = execute_query(q, (tid, title, description, start_dt, end_dt, all_day, color), returning=True)
    return jsonify({"id": new_id})

# API: update event (move/resize or edit)
@calendar_bp.route('/api/calendar/event/<int:event_id>', methods=['PUT'])
def api_calendar_update_event(event_id):
    if 'teacher_id' not in session:
        return jsonify({"error":"unauth"}), 401
    tid = session['teacher_id']
    body = request.get_json() or {}
    title = body.get('title')
    description = body.get('description')
    start = body.get('start')
    end = body.get('end')
    all_day = body.get('allDay')
    color = body.get('color')

    # build dynamic update
    updates = []
    params = []
    if title is not None:
        updates.append("title=%s"); params.append(title)
    if description is not None:
        updates.append("description=%s"); params.append(description)
    if start is not None:
        try:
            start_dt = datetime.fromisoformat(start)
        except Exception:
            return jsonify({"error":"bad start"}), 400
        updates.append("start_ts=%s"); params.append(start_dt)
    if end is not None:
        try:
            end_dt = datetime.fromisoformat(end)
        except Exception:
            return jsonify({"error":"bad end"}), 400
        updates.append("end_ts=%s"); params.append(end_dt)
    if all_day is not None:
        updates.append("all_day=%s"); params.append(bool(all_day))
    if color is not None:
        updates.append("color=%s"); params.append(color)

    if not updates:
        return jsonify({"ok": True, "message": "nothing changed"})

    params.extend([datetime.now(), event_id, tid])
    q = f"UPDATE TeacherCalendar SET {', '.join(updates)}, updated_at=%s WHERE id=%s AND teacher_id=%s"
    execute_query(q, tuple(params))
    return jsonify({"ok": True})

# API: delete event
@calendar_bp.route('/api/calendar/event/<int:event_id>', methods=['DELETE'])
def api_calendar_delete_event(event_id):
    if 'teacher_id' not in session:
        return jsonify({"error":"unauth"}), 401
    tid = session['teacher_id']
    q = "DELETE FROM TeacherCalendar WHERE id=%s AND teacher_id=%s"
    execute_query(q, (event_id, tid))
    return jsonify({"ok": True})



# ---------------- CREATE ASSIGNMENT ----------------
@app.route('/teacher/create_assignment', methods=['POST'])
def create_assignment():
    if 'teacher_id' not in session:
        return redirect('/')
    course_id = request.form['course_id']
    title = request.form['title']
    description = request.form.get('description')
    raw_date = request.form['due_date']  # expects datetime-local
    due = datetime.fromisoformat(raw_date) if raw_date else None

    Assignment.create(course_id, session['teacher_id'], title, description, due)
    return redirect('/teacher/dashboard')

# ---------------- TEACHER ANNOUNCEMENT POST ----------------
@app.route('/teacher/post', methods=['POST'])
def teacher_post():
    if 'teacher_id' not in session:
        return redirect('/')
    content = request.form.get('content')
    if not content or not content.strip():
        return redirect('/teacher/dashboard')
    TeacherPost.create(session['teacher_id'], content)
    return redirect('/teacher/dashboard')

# ---------------- ADD COURSE TO TEACHER ----------------
@app.route('/teacher/add_course', methods=['POST'])
def teacher_add_course():
    if 'teacher_id' not in session:
        return redirect('/')
    course_id = request.form['course_id']
    Teacher.assign_to_course(session['teacher_id'], course_id)
    return redirect('/teacher/dashboard')

# ---------------- VIEW SUBMISSIONS ----------------
@app.route('/teacher/submissions/<int:assignment_id>')
def view_submissions(assignment_id):
    submissions = execute_query("""
        SELECT s.id, st.name, s.file_path, s.submitted_at, s.marks
        FROM Submissions s
        JOIN Students st ON s.student_id = st.id
        WHERE s.assignment_id=%s
    """, (assignment_id,), fetch=True)

    assignment = execute_query("SELECT title, description, due_date FROM Assignments WHERE id=%s", (assignment_id,), fetch=True)
    return render_template('teacher_submissions.html', submissions=submissions, assignment=assignment[0] if assignment else None)

# ---------------- GRADE SUBMISSION ----------------
@app.route('/teacher/grade_submission', methods=['POST'])
def grade_submission():
    submission_id = request.form['submission_id']
    marks = request.form['marks']

    # Use model method so notification + avg update happen consistently
    Teacher.grade_submission(submission_id, marks)

    return redirect(request.referrer or '/teacher/dashboard')

# ---------------- ATTENDANCE VIEW ----------------
@app.route('/teacher/attendance/<int:course_id>')
def teacher_attendance_view(course_id):
    date = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
    students = AttendanceModel.get_course_attendance_for_date(course_id, date)
    course = execute_query("SELECT course_name FROM Courses WHERE id=%s", (course_id,), fetch=True)
    course_name = course[0][0] if course else "Course"

    return render_template('teacher_mark_attendance.html', course_id=course_id,course_name=course_name, date=date, students=students)

# ---------------- ATTENDANCE MARK ----------------
@app.route('/teacher/attendance/<int:course_id>', methods=['POST'])
def teacher_mark_attendance(course_id):
    date = request.form.get('date') or datetime.today().strftime('%Y-%m-%d')
    records = []
    for k, v in request.form.items():
        if k.startswith("present_"):
            sid = int(k.split("_")[1])
            records.append({'student_id': sid, 'present': 1})
    AttendanceModel.mark_attendance_bulk(course_id, date, records)
    flash("Attendance saved!", "success")
    return redirect(url_for('teacher_attendance_view', course_id=course_id, date=date))

# ---------------- ML PREDICT ----------------
@app.route('/ml/run_predictions', methods=['POST'])
def run_ml_predictions():
    from ml_model import predict_all_students
    threshold = float(request.form.get('notify_threshold', 0.6))
    results = predict_all_students(threshold)
    for r in results:
        Notification.create(r['student_id'], f"Risk alert: {r['risk_label']} ({r['risk_score']:.2f})")
    return jsonify({"count": len(results)})

# ---------------- SERVE UPLOADS ----------------
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

