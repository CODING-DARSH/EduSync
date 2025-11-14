from flask import Flask, render_template, request, redirect, session, jsonify
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
    TeacherPost      # IMPORTANT
)

from db import execute_query
from datetime import datetime
from flask import send_from_directory, url_for, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "supersecretkey123"
app.jinja_env.filters['zip'] = zip


# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template('login.html')


# ---------------- STUDENT UPLOAD ----------------
@app.route('/student/upload', methods=['POST'])
def student_upload():
    file = request.files['file']
    assignment_id = request.form.get('assignment_id')
    student_id = session['student_id']

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
        student_id = Student.register(
            request.form['name'],
            request.form['email'],
            request.form['phone'],
            request.form['password']
        )
        return f"Registration successful! Your student ID is {student_id}. <a href='/'>Login</a>"
    return render_template('register.html')


# ---------------- STUDENT LOGIN ----------------
@app.route('/student/login', methods=['POST'])
def student_login():
    student_id = request.form['id']
    password = request.form['password']
    user = Student.login(student_id, password)
    if user:
        session['student_id'] = user[0]
        return redirect('/student/dashboard')
    return "Invalid credentials"


# ---------------- STUDENT REQUEST OTP ----------------
@app.route('/student/request-otp', methods=['POST'])
def request_otp():
    student_id = request.form.get('id')
    form_email = request.form.get('email')
    form_phone = request.form.get('phone')

    if not student_id:
        return "Missing student id", 400

    otp = OTP.generate_otp(student_id)

    try:
        if form_email:
            send_email(form_email, "Your Login OTP", f"Your OTP is {otp}")

        elif form_phone:
            send_sms(form_phone, f"Your OTP is {otp}")

        else:
            data = execute_query(
                "SELECT email, phone FROM Students WHERE id=%s",
                (student_id,), fetch=True
            )

            if not data:
                return "Student not found", 404

            email, phone = data[0]

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
        student_id=student_id,
        message="OTP sent successfully!"
    )


# ---------------- VERIFY OTP ----------------
@app.route('/student/verify-otp', methods=['POST'])
def verify_otp():
    if OTP.verify_otp(request.form['id'], request.form['otp']):
        session['student_id'] = request.form['id']
        return redirect('/student/dashboard')
    else:
        return "Invalid or expired OTP."


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
    return render_template(
        'student_profile.html',
        student=Student.get_details(session['student_id'])
    )


# ---------------- UPDATE PASSWORD ----------------
@app.route('/student/update_password', methods=['POST'])
def update_password():
    if 'student_id' not in session:
        return redirect('/')
    Student.change_password(
        session['student_id'],
        request.form['old_password'],
        request.form['new_password']
    )
    return redirect('/student/profile')


# ---------------- EXPORT CSV ----------------
@app.route('/student/export')
def student_export():
    Student.export_csv(session['student_id'])
    return "Your report has been downloaded successfully!"


# ---------------- STUDENT NOTIFICATIONS ----------------
@app.route('/student/notifications')
def student_notifications():
    return render_template(
        'student_notifications.html',
        notifications=Student.get_notifications(session['student_id'])
    )


# ---------------- STUDENT SUBMISSIONS ----------------
@app.route('/student/submissions')
def student_submissions():
    return render_template(
        'student_submissions.html',
        submissions=Submission.get_for_student(session['student_id'])
    )


# ---------------- ENROLL COURSE ----------------
@app.route('/student/enroll', methods=['POST'])
def enroll():
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
    return "Invalid credentials"


# ---------------- TEACHER REGISTER ----------------
@app.route('/teacher/register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        teacher_id = Teacher.register(
            request.form['name'],
            request.form['password']
        )
        return f"Registered! Your Teacher ID is {teacher_id}. <a href='/'>Login</a>"
    return render_template('teacher_register.html')


# ---------------- TEACHER DASHBOARD ----------------
@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect('/')

    tid = session['teacher_id']

    teacher = execute_query(
        "SELECT id, name FROM Teachers WHERE id=%s",
        (tid,), fetch=True
    )
    teacher = teacher[0] if teacher else None

    students = execute_query("""
        SELECT s.id, s.name, c.course_name, c.id
        FROM Students s
        JOIN StudentCourses sc ON s.id = sc.student_id
        JOIN Courses c ON sc.course_id = c.id
        JOIN TeacherCourses tc ON c.id = tc.course_id
        WHERE tc.teacher_id = %s
    """, (tid,), fetch=True)

    courses = Teacher.get_courses(tid)

    assignments = execute_query("""
        SELECT id, title, due_date
        FROM Assignments
        WHERE teacher_id = %s
        ORDER BY due_date DESC
    """, (tid,), fetch=True)

    posts = TeacherPost.get_for_teacher(tid)

    attendance_summary = []
    for cid, cname in courses:
        data = execute_query("""
            SELECT s.name, ROUND(AVG(a.present)*100,2)
            FROM Attendance a
            JOIN Students s ON a.student_id = s.id
            WHERE a.course_id = %s
            GROUP BY s.name
            ORDER BY s.name
        """, (cid,), fetch=True)

        attendance_summary.append({
            'course_id': cid,
            'course_name': cname,
            'records': [
                {'name': r[0], 'percent': float(r[1] or 0)}
                for r in data
            ]
        })

    notifications = execute_query("""
        SELECT message, TO_CHAR(created_at,'YYYY-MM-DD HH24:MI')
        FROM TeacherNotifications
        WHERE teacher_id = %s
        ORDER BY created_at DESC
    """, (tid,), fetch=True)

    return render_template(
        'teacher_dashboard.html',
        teacher=teacher,
        students=students,
        courses=courses,
        assignments=assignments,
        posts=posts,
        notifications=notifications,
        attendance_summary=attendance_summary
    )


# ---------------- CREATE ASSIGNMENT ----------------
@app.route('/teacher/create_assignment', methods=['POST'])
def create_assignment():
    if 'teacher_id' not in session:
        return redirect('/')

    course_id = request.form['course_id']
    title = request.form['title']
    description = request.form.get('description')
    raw_date = request.form['due_date']  # datetime-local

    due = datetime.fromisoformat(raw_date)

    Assignment.create(
        course_id,
        session['teacher_id'],
        title,
        description,
        due
    )
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

    assignment = execute_query("""
        SELECT title, description, due_date
        FROM Assignments
        WHERE id=%s
    """, (assignment_id,), fetch=True)

    return render_template(
        'teacher_submissions.html',
        submissions=submissions,
        assignment=assignment[0] if assignment else None
    )


# ---------------- GRADE SUBMISSION ----------------
@app.route('/teacher/grade_submission', methods=['POST'])
def grade_submission():
    submission_id = request.form['submission_id']
    marks = request.form['marks']

    execute_query(
        "UPDATE Submissions SET marks=%s WHERE id=%s",
        (marks, submission_id)
    )

    data = execute_query("""
        SELECT s.student_id, a.course_id
        FROM Submissions s
        JOIN Assignments a ON s.assignment_id=a.id
        WHERE s.id=%s
    """, (submission_id,), fetch=True)

    if data:
        sid, cid = data[0]
        execute_query("""
            UPDATE StudentCourses
            SET marks = (
                SELECT ROUND(AVG(s.marks)::numeric,2)
                FROM Submissions s
                JOIN Assignments a ON s.assignment_id = a.id
                WHERE s.student_id=%s AND a.course_id=%s AND s.marks IS NOT NULL
            )
            WHERE student_id=%s AND course_id=%s
        """, (sid, cid, sid, cid))

    return redirect(request.referrer or '/teacher/dashboard')


# ---------------- ATTENDANCE VIEW ----------------
@app.route('/teacher/attendance/<int:course_id>')
def teacher_attendance_view(course_id):
    date = request.args.get('date') or datetime.today().strftime('%Y-%m-%d')
    students = AttendanceModel.get_course_attendance_for_date(course_id, date)

    return render_template(
        'teacher_mark_attendance.html',
        course_id=course_id,
        date=date,
        students=students
    )


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

    return redirect(
        url_for('teacher_attendance_view', course_id=course_id, date=date)
    )


# ---------------- ML PREDICT ----------------
@app.route('/ml/run_predictions', methods=['POST'])
def run_ml_predictions():
    from ml_model import predict_all_students
    threshold = float(request.form.get('notify_threshold', 0.6))
    results = predict_all_students(threshold)

    for r in results:
        Notification.create(
            r['student_id'],
            f"Risk alert: {r['risk_label']} ({r['risk_score']:.2f})"
        )

    return jsonify({"count": len(results)})


# ---------------- SERVE UPLOADS ----------------
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


# ---------------- MAIN ----------------
if __name__ == '__main__':
    app.run(debug=True)
