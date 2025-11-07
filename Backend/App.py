from flask import Flask, render_template, request, redirect, session, jsonify
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from models import Student, Teacher, Admin, OTP, send_email_otp, send_sms_otp, Assignment, Submission,Notification
from db import execute_query
from datetime import datetime
from flask import send_from_directory, request, redirect, url_for, flash
from flask import send_from_directory
from werkzeug.utils import secure_filename
app = Flask(__name__)
app.secret_key = "supersecretkey123"

# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template('login.html')
@app.route('/student/upload', methods=['POST'])
def student_upload():
    file = request.files['file']
    assignment_id = request.form.get('assignment_id')
    student_id = session['student_id']

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        # Save path to DB
        Submission.submit(assignment_id, student_id, filename)
        flash("✅ Assignment uploaded successfully.", "success")
    else:
        flash("❌ No file selected.", "error")

    return redirect(url_for('student_dashboard'))
# ---------------- STUDENT REGISTER ----------------
@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        student_id = Student.register(name, email, phone, password)
        return f"Registration successful! Your student ID is {student_id}. <a href='/'>Login</a>"
    return render_template('register.html')


# ---------------- STUDENT LOGIN (PASSWORD) ----------------
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
    student_id = request.form['id']
    form_email = request.form.get('email')
    form_phone = request.form.get('phone')

    otp = OTP.generate_otp(student_id)

    # ✅ send OTP using available contact info
    if form_email:
        send_email_otp(form_email, otp)
    elif form_phone:
        try:
            send_sms_otp(form_phone, otp)
        except Exception as e:
            print(f"❌ SMS send failed, falling back to email (if exists): {e}")
            if form_email:
                send_email_otp(form_email, otp)
            else:
                print("📱 SMS skipped (no Twilio number). Sent via email only.")
    else:
        # fallback to whatever is in DB
        q = "SELECT email, phone FROM Students WHERE id=:1"
        data = execute_query(q, (student_id,), fetch=True)
        if not data:
            return "Student not found", 404
        email, phone = data[0]

        if email:
            send_email_otp(email, otp)
        elif phone:
            try:
                send_sms_otp(phone, otp)
            except Exception as e:
                print(f"❌ SMS send failed, fallback to email if possible: {e}")
                if email:
                    send_email_otp(email, otp)
                else:
                    print("📱 SMS skipped (no Twilio number). Sent via email only.")
        else:
            return "No email or phone number on record."

    # after sending, redirect or render OTP entry form
    # ✅ show OTP entry form now with message
    return render_template(
    "student_verify_otp.html",
    student_id=student_id,
    message="✅ OTP sent successfully! Please check your email or phone."
)


# ---------------- STUDENT VERIFY OTP ----------------
@app.route('/student/verify-otp', methods=['POST'])
def verify_otp():
    student_id = request.form['id']
    user_otp = request.form['otp']

    if OTP.verify_otp(student_id, user_otp):
        session['student_id'] = student_id
        return redirect('/student/dashboard')
    else:
        return "Invalid or expired OTP."
    
@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect('/')

    student_id = session['student_id']

    # ✅ Get student details
    student = Student.get_details(student_id)

    # ✅ Get enrolled courses
    courses = Student.show_courses(student_id)

    # ✅ Get assignments (joined with submissions + marks)
    assignments = execute_query("""
        SELECT 
            a.id, 
            a.title, 
            a.due_date, 
            s.file_path, 
            s.marks
        FROM Assignments a
        JOIN StudentCourses sc ON a.course_id = sc.course_id
        LEFT JOIN Submissions s ON s.assignment_id = a.id AND s.student_id = :1
        WHERE sc.student_id = :1
        ORDER BY a.due_date
    """, (student_id,), fetch=True)

    # ✅ Course averages for performance chart
    grades_data = Student.get_course_grades(student_id)
    chart_labels = [row[0] for row in grades_data]
    chart_data = [float(row[1]) for row in grades_data]

    # ✅ Notifications (from new table)
    try:
        notifications = Notification.get_for_student(student_id)
    except Exception:
        notifications = []

    return render_template(
        "student_dashboard.html",
        student=student,
        courses=courses,
        assignments=assignments,
        notifications=notifications,
        chart_labels=chart_labels,
        chart_data=chart_data
    )



# ---------------- STUDENT PROFILE ----------------
@app.route('/student/profile')
def student_profile():
    if 'student_id' not in session:
        return redirect('/')
    student = Student.get_details(session['student_id'])
    return render_template('student_profile.html', student=student)

# ---------------- UPDATE PASSWORD ----------------
@app.route('/student/update_password', methods=['POST'])
def update_password():
    if 'student_id' not in session:
        return redirect('/')
    old = request.form['old_password']
    new = request.form['new_password']
    success = Student.change_password(session['student_id'], old, new)
    msg = "Password updated!" if success else "Incorrect old password."
    return redirect('/student/profile')

# ---------------- EXPORT STUDENT REPORT ----------------
@app.route('/student/export')
def student_export():
    if 'student_id' not in session:
        return redirect('/')
    sid = session['student_id']
    Student.export_csv(sid)
    return "Your report has been downloaded successfully!"

# ---------------- STUDENT NOTIFICATIONS ----------------
@app.route('/student/notifications')
def student_notifications():
    if 'student_id' not in session:
        return redirect('/')
    notes = Student.get_notifications(session['student_id'])
    return render_template('student_notifications.html', notifications=notes)
@app.route('/student/submissions')
def student_submissions():
    if 'student_id' not in session:
        return redirect('/')
    data = Submission.get_for_student(session['student_id'])
    return render_template('student_submissions.html', submissions=data)

# ---------------- ENROLL COURSE ----------------
@app.route('/student/enroll', methods=['POST'])
def enroll():
    if 'student_id' not in session:
        return "Not logged in"
    course_id = request.form['course_id']
    Student.enroll(session['student_id'], course_id)
    return redirect('/student/dashboard')

# ---------------- LOGOUT ----------------
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/')

# ---------------- TEACHER ASSIGN GRADE ----------------
@app.route('/teacher/grade', methods=['POST'])
def assign_grade():
    teacher_id = session.get('teacher_id')  # make sure you store this at login
    student_id = request.form['student_id']
    course_id = request.form['course_id']
    grade = request.form['marks']

    # ✅ check teacher-course match
    allowed = execute_query(
        "SELECT 1 FROM TeacherCourses WHERE teacher_id=:1 AND course_id=:2",
        (teacher_id, course_id),
        fetch=True
    )
    if not allowed:
        return "❌ You are not authorized to grade this course.", 403

    Teacher.assign_grade(teacher_id, student_id, course_id, grade)
    return jsonify({"message": "✅ Grade assigned successfully"})
@app.route('/teacher/add_course', methods=['POST'])
def teacher_add_course():
    if 'teacher_id' not in session:
        return redirect('/')
    if not 'teacher_id':
        return redirect('/')

    course_id = request.form['course_id']
    Teacher.assign_to_course(session['teacher_id'], course_id)
    return redirect('/teacher/dashboard')

@app.route('/teacher/register', methods=['GET', 'POST'])
def teacher_register():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        teacher_id = Teacher.register(name, password)
        return f"✅ Registration successful! Your Teacher ID is <b>{teacher_id}</b>. <a href='/'>Login</a>"
    return render_template('teacher_register.html')

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if 'teacher_id' not in session:
        return redirect('/')

    teacher_id = session['teacher_id']

    # Fetch teacher details
    teacher = execute_query(
        "SELECT id, name FROM Teachers WHERE id=:1",
        (teacher_id,),
        fetch=True
    )
    teacher = teacher[0] if teacher else None

    # Get teacher’s students
    q = """
        SELECT s.id, s.name, c.course_name, c.id
        FROM Students s
        JOIN StudentCourses sc ON s.id = sc.student_id
        JOIN Courses c ON sc.course_id = c.id
        JOIN TeacherCourses tc ON c.id = tc.course_id
        WHERE tc.teacher_id = :1
    """
    students = execute_query(q, (teacher_id,), fetch=True)

    # Fetch teacher's assigned courses
    courses = Teacher.get_courses(teacher_id)

    # Fetch assignments
    assignments = execute_query(
        "SELECT id, title, due_date FROM Assignments WHERE teacher_id=:1",
        (teacher_id,),
        fetch=True
    )

    # Fetch posts
    posts = execute_query(
        "SELECT content, created_at FROM TeacherPosts WHERE teacher_id=:1 ORDER BY created_at DESC",
        (teacher_id,),
        fetch=True
    )

    return render_template(
        'teacher_dashboard.html',
        teacher=teacher,   # ✅ added this line
        students=students,
        courses=courses,
        assignments=assignments,
        posts=posts
    )


@app.route('/teacher/login', methods=['POST'])
def teacher_login():
    teacher_id = request.form['id']
    password = request.form['password']
    user = Teacher.login(teacher_id, password)

    if user:
        session['teacher_id'] = user[0]
        return redirect('/teacher/dashboard')
    else:
        return "Invalid credentials"

app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.jinja_env.filters['zip'] = zip

@app.route('/student/upload', methods=['POST'])
def upload_assignment():
    if 'student_id' not in session:
        return redirect('/')
    
    assignment_id = request.form['assignment_id']
    file = request.files['file']
    if not file:
        return "No file selected"

    filename = f"{session['student_id']}_{assignment_id}_{file.filename}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    Submission.submit(assignment_id, session['student_id'], path)
    return "Assignment uploaded successfully!"


# ---------------- ADMIN LOGIN ----------------
@app.route('/admin/login', methods=['POST'])
def admin_login():
    username = request.form['username']
    password = request.form['password']
    if Admin.login(username, password):
        session['admin'] = username
        return redirect('/admin/dashboard')
    return "Invalid admin credentials"

# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect('/')
    students = Admin.show_all_students()
    return render_template('admin_dashboard.html', students=students)


@app.route('/teacher/create_assignment', methods=['POST'])
def create_assignment():
    if 'teacher_id' not in session:
        return redirect('/')

    title = request.form['title']
    description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    course_id = request.form['course_id']

    # ✅ convert date string (YYYY-MM-DD) to datetime object
    due_date = None
    if due_date_str:
        due_date = datetime.strptime(due_date_str, "%Y-%m-%d")

    Assignment.create(course_id, session['teacher_id'], title, description, due_date)
    return redirect('/teacher/dashboard')

@app.route('/teacher/post', methods=['POST'])
def teacher_post():
    if 'teacher_id' not in session:
        return redirect('/')
    content = request.form['content']
    q = "INSERT INTO TeacherPosts (id, teacher_id, content, created_at) VALUES ((SELECT NVL(MAX(id),0)+1 FROM TeacherPosts), :1, :2, SYSDATE)"
    execute_query(q, (session['teacher_id'], content))
    return redirect('/teacher/dashboard')
@app.route('/teacher/submissions/<int:assignment_id>')
def view_submissions(assignment_id):
    if 'teacher_id' not in session:
        return redirect('/')

    # Fetch all submissions for that assignment
    q = """
        SELECT s.id, st.name, s.file_path, s.submitted_at, s.marks
        FROM Submissions s
        JOIN Students st ON s.student_id = st.id
        WHERE s.assignment_id = :1
    """
    submissions = execute_query(q, (assignment_id,), fetch=True)

    # Also fetch assignment info (optional)
    assignment = execute_query(
        "SELECT title, description, due_date FROM Assignments WHERE id=:1",
        (assignment_id,),
        fetch=True
    )
    assignment = assignment[0] if assignment else None

    return render_template('teacher_submissions.html',
                           submissions=submissions,
                           assignment=assignment)


UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")  # adjust to your actual upload dir
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# --------- Serve uploaded assignment files ---------
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    try:
        return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)
    except Exception as e:
        print(f"❌ File download error: {e}")
        return "File not found", 404


# --------- Grade a specific student submission ---------
@app.route('/teacher/grade_submission', methods=['POST'])
def grade_submission():
    if 'teacher_id' not in session:
        return redirect('/')

    submission_id = request.form['submission_id']
    marks = request.form['marks']

    # ✅ Update marks for this submission
    execute_query("UPDATE Submissions SET marks=:1 WHERE id=:2", (marks, submission_id))

    # ✅ Fetch student_id and course_id linked to this submission
    student_course_data = execute_query("""
        SELECT s.student_id, a.course_id
        FROM Submissions s
        JOIN Assignments a ON s.assignment_id = a.id
        WHERE s.id = :1
    """, (submission_id,), fetch=True)

    if student_course_data:
        student_id, course_id = student_course_data[0]

        # ✅ After grading one assignment, auto-update student's course average
        execute_query("""
            UPDATE StudentCourses
            SET marks = (
                SELECT ROUND(AVG(s.marks), 2)
                FROM Submissions s
                JOIN Assignments a ON s.assignment_id = a.id
                WHERE s.student_id = :1 AND a.course_id = :2 AND s.marks IS NOT NULL
            )
            WHERE student_id = :1 AND course_id = :2
        """, (student_id, course_id))

    return redirect(request.referrer or '/teacher/dashboard')



# ---------------- MAIN ----------------
if __name__ == '__main__':
    app.run(debug=True)


