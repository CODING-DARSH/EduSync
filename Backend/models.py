# models.py (fixed for Postgres)
import os
import random
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from twilio.rest import Client  # optional: prints dev-mode if creds missing
from datetime import datetime, timedelta

from db import execute_query

load_dotenv()

# ---------------- EMAIL / SMS UTILITIES ----------------
def send_email(to_address, subject, body):
    sender = os.getenv("EMAIL_ADDR")
    app_password = os.getenv("EMAIL_APP_PASSWORD")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_address

    if not sender or not app_password:
        print(f"📧 [DEV MODE] send_email to {to_address} | Subject: {subject} | Body: {body}")
        return

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, app_password)
            server.send_message(msg)
        print(f"✅ Email sent to: {to_address}")
    except Exception as e:
        print(f"❌ Email send error: {e}")

def send_sms(to_phone, message):
    sid = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not (sid and token and from_number):
        print(f"📱 [DEV MODE] send_sms to {to_phone}: {message}")
        return

    try:
        client = Client(sid, token)
        client.messages.create(
            body=message,
            from_=from_number,
            to=f"+91{to_phone}" if not to_phone.startswith("+") else to_phone,
        )
        print(f"✅ SMS sent to: {to_phone}")
    except Exception as e:
        print(f"❌ SMS send error: {e}")

def send_notification_contacts_for_student(student_id, subject, message):
    """
    Fetch student's email/phone and send the notification via email and/or SMS.
    """
    row = execute_query("SELECT email, phone FROM Students WHERE id=%s", (student_id,), fetch=True)
    if not row:
        print(f"⚠️ No contact info for student {student_id}")
        return
    email, phone = row[0]
    if email:
        send_email(email, subject, message)
    if phone:
        send_sms(phone, message)

# ---------------- STUDENT MODEL ----------------
class Student:
    @staticmethod
    def register(name, email, phone, password):
        q = "INSERT INTO Students (name, email, phone, password) VALUES (%s, %s, %s, %s) RETURNING id"
        new_id = execute_query(q, (name, email, phone, password), returning=True)
        print(f"✅ Student registered with ID: {new_id}")
        return new_id

    @staticmethod
    def login(student_id, password):
        q = "SELECT id, name FROM Students WHERE id=%s AND password=%s"
        data = execute_query(q, (student_id, password), fetch=True)
        return data[0] if data else None

    @staticmethod
    def change_password(student_id, old_password, new_password):
        q = "SELECT password FROM Students WHERE id=%s"
        data = execute_query(q, (student_id,), fetch=True)
        if data and data[0][0] == old_password:
            execute_query("UPDATE Students SET password=%s WHERE id=%s", (new_password, student_id))
            return True
        return False

    @staticmethod
    def get_details(student_id):
        q = "SELECT id, name, grades FROM Students WHERE id=%s"
        data = execute_query(q, (student_id,), fetch=True)
        return data[0] if data else None

    @staticmethod
    def enroll(student_id, course_id):
        execute_query("INSERT INTO StudentCourses (student_id, course_id) VALUES (%s, %s)", (student_id, course_id))

    @staticmethod
    def show_courses(student_id):
        q = """
        SELECT c.course_name
        FROM Courses c
        JOIN StudentCourses sc ON c.id = sc.course_id
        WHERE sc.student_id = %s
        """
        data = execute_query(q, (student_id,), fetch=True)
        return [row[0] for row in data] if data else []

    @staticmethod
    def get_course_grades(student_id):
        q = """
        SELECT c.course_name, sc.marks
        FROM Courses c
        JOIN StudentCourses sc ON c.id = sc.course_id
        WHERE sc.student_id = %s
        """
        data = execute_query(q, (student_id,), fetch=True)
        return [(row[0], row[1] or 0) for row in data] if data else []

    @staticmethod
    def export_csv(student_id):
        data = Student.get_course_grades(student_id)
        filename = f"student_{student_id}_report.csv"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("Course,Marks\n")
            for d in data:
                f.write(f"{d[0]},{d[1]}\n")
        print(f"📁 Exported report: {filename}")

    @staticmethod
    def get_notifications(student_id):
        q = """
        SELECT message, to_char(created_at,'YYYY-MM-DD HH24:MI')
        FROM Notifications
        WHERE student_id=%s
        ORDER BY created_at DESC
        """
        return execute_query(q, (student_id,), fetch=True)

# ---------------- TEACHER NOTIFICATIONS ----------------
class TeacherNotification:
    @staticmethod
    def create(teacher_id, message):
        q = "INSERT INTO TeacherNotifications (teacher_id, message, created_at) VALUES (%s, %s, NOW()) RETURNING id"
        new_id = execute_query(q, (teacher_id, message), returning=True)
        return new_id

# ---------------- NOTIFICATIONS MODEL ----------------
class Notification:
    @staticmethod
    def create(student_id, message):
        q = "INSERT INTO Notifications (student_id, message, created_at) VALUES (%s, %s, NOW()) RETURNING id"
        new_id = execute_query(q, (student_id, message), returning=True)
        print(f"🔔 Notification created (id={new_id}) for Student {student_id}: {message}")
        # also send out realtime contact notification (optional)
        send_notification_contacts_for_student(student_id, "Notification from Student Portal", message)
        return new_id

    @staticmethod
    def get_for_student(student_id):
        q = """
        SELECT message, to_char(created_at,'YYYY-MM-DD HH24:MI')
        FROM Notifications
        WHERE student_id=%s
        ORDER BY created_at DESC
        """
        return execute_query(q, (student_id,), fetch=True)

# ---------------- TEACHER MODEL ----------------
class Teacher:
    @staticmethod
    def register(name, password):
        q = "INSERT INTO Teachers (name, password) VALUES (%s, %s) RETURNING id"
        new_id = execute_query(q, (name, password), returning=True)
        print(f"✅ Teacher registered with ID: {new_id}")
        return new_id

    @staticmethod
    def get_courses(teacher_id):
        q = """SELECT c.id, c.course_name
               FROM Courses c
               JOIN TeacherCourses tc ON c.id = tc.course_id
               WHERE tc.teacher_id = %s"""
        return execute_query(q, (teacher_id,), fetch=True)

    @staticmethod
    def login(teacher_id, password):
        q = "SELECT id, name FROM Teachers WHERE id=%s AND password=%s"
        data = execute_query(q, (teacher_id, password), fetch=True)
        return data[0] if data else None

    @staticmethod
    def grade_submission(submission_id, marks):
        execute_query("UPDATE Submissions SET marks=%s WHERE id=%s", (marks, submission_id))
        data = execute_query("""
            SELECT s.student_id, a.course_id
            FROM Submissions s
            JOIN Assignments a ON s.assignment_id=a.id
            WHERE s.id=%s
        """, (submission_id,), fetch=True)
        if not data:
            print("❌ No related student/course found.")
            return

        student_id, course_id = data[0]
        # recompute average marks for the student in that course
        execute_query("""
            UPDATE StudentCourses
            SET marks = (
                SELECT ROUND(AVG(s.marks)::numeric, 2)
                FROM Submissions s
                JOIN Assignments a ON s.assignment_id=a.id
                WHERE s.student_id=%s AND a.course_id=%s AND s.marks IS NOT NULL
            )
            WHERE student_id=%s AND course_id=%s
        """, (student_id, course_id, student_id, course_id))
        Notification.create(student_id, f"✅ Your submission for Course {course_id} has been graded. Marks: {marks}")

    @staticmethod
    def assign_to_course(teacher_id, course_id):
        q = "INSERT INTO TeacherCourses (teacher_id, course_id) VALUES (%s, %s) RETURNING id"
        new_id = execute_query(q, (teacher_id, course_id), returning=True)
        return new_id
class TeacherPost:
    @staticmethod
    def create(teacher_id, message):
        # Save post
        post_id = execute_query(
            "INSERT INTO TeacherPosts (teacher_id, message, created_at) VALUES (%s, %s, NOW()) RETURNING id",
            (teacher_id, message),
            returning=True
        )

        # ALSO notify all students of this teacher
        students = execute_query("""
            SELECT sc.student_id
            FROM StudentCourses sc
            JOIN TeacherCourses tc ON sc.course_id = tc.course_id
            WHERE tc.teacher_id = %s
        """, (teacher_id,), fetch=True)

        for (sid,) in students:
            Notification.create(sid, f"📢 Announcement from your teacher: {message}")

        return post_id

    @staticmethod
    def get_for_teacher(teacher_id):
        return execute_query("""
            SELECT id, message, to_char(created_at,'YYYY-MM-DD HH24:MI')
            FROM TeacherPosts
            WHERE teacher_id = %s
            ORDER BY created_at DESC
        """, (teacher_id,), fetch=True)





# ---------------- ADMIN MODEL ----------------
class Admin:
    @staticmethod
    def login(username, password):
        q = "SELECT username FROM Admins WHERE username=%s AND password=%s"
        data = execute_query(q, (username, password), fetch=True)
        return bool(data)

    @staticmethod
    def show_all_students():
        q = "SELECT id, name, grades FROM Students"
        return execute_query(q, fetch=True)

# ---------------- OTP MODEL ----------------
class OTP:
    @staticmethod
    def generate_otp(student_id):
        otp = str(random.randint(100000, 999999))
        expires_at = datetime.now() + timedelta(minutes=5)
        q = "INSERT INTO OTP_CODES (student_id, otp_code, expires_at) VALUES (%s, %s, %s) RETURNING id"
        new_id = execute_query(q, (student_id, otp, expires_at), returning=True)
        print(f"✅ OTP {otp} created (id={new_id}) for Student {student_id}")
        return otp

    @staticmethod
    def verify_otp(student_id, otp_code):
        q = "SELECT otp_code, expires_at FROM OTP_CODES WHERE student_id=%s ORDER BY expires_at DESC LIMIT 1"
        data = execute_query(q, (student_id,), fetch=True)
        if not data:
            return False
        otp, expiry = data[0]
        return otp == otp_code and datetime.now() < expiry

# ---------------- ASSIGNMENTS MODEL ----------------
class Assignment:
    @staticmethod
    def create(course_id, teacher_id, title, description, due_date):
        q = """
        INSERT INTO Assignments (course_id, teacher_id, title, description, due_date)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """
        new_id = execute_query(q, (course_id, teacher_id, title, description, due_date), returning=True)
        # notify students in the course
        students = execute_query("SELECT student_id FROM StudentCourses WHERE course_id=%s", (course_id,), fetch=True)
        if students:
            for (sid,) in students:
                Notification.create(sid, f"🆕 New assignment posted: {title} (Due: {due_date})")
        print(f"✅ Assignment {new_id} created for Course {course_id}")
        return new_id

    @staticmethod
    def get_for_teacher(teacher_id):
        q = "SELECT id, title, description, due_date FROM Assignments WHERE teacher_id=%s"
        return execute_query(q, (teacher_id,), fetch=True)

# ---------------- SUBMISSIONS MODEL ----------------
class Submission:
    @staticmethod
    def submit(assignment_id, student_id, file_path):
        q = """
        INSERT INTO Submissions (assignment_id, student_id, file_path, submitted_at)
        VALUES (%s, %s, %s, NOW()) RETURNING id
        """
        new_id = execute_query(q, (assignment_id, student_id, file_path), returning=True)
        Notification.create(student_id, f"📤 Assignment {assignment_id} submitted successfully.")
        print(f"✅ Submission {new_id} saved for Student {student_id}")
        return new_id

    @staticmethod
    def get_for_student(student_id):
        q = """
        SELECT s.id, a.id, a.title, s.file_path, s.submitted_at, s.marks
        FROM Submissions s
        JOIN Assignments a ON s.assignment_id = a.id
        WHERE s.student_id = %s
        """
        return execute_query(q, (student_id,), fetch=True)

# ---------------- ATTENDANCE MODEL ----------------
class AttendanceModel:
    @staticmethod
    def mark_attendance_bulk(course_id, date_str, attendance_list):
        """
        attendance_list: list of dicts {'student_id': id, 'present': True/False}
        date_str: 'YYYY-MM-DD' or a date object; here we expect string for simplicity
        """
        for rec in attendance_list:
            sid = rec['student_id']
            present = 1 if rec.get('present') else 0
            exists = execute_query(
                "SELECT id FROM Attendance WHERE student_id=%s AND course_id=%s AND DATE(date_marked)=%s",
                (sid, course_id, date_str), fetch=True
            )
            if exists:
                execute_query(
                    "UPDATE Attendance SET present=%s, created_at=NOW() WHERE id=%s",
                    (present, exists[0][0])
                )
            else:
                execute_query(
                    "INSERT INTO Attendance (student_id, course_id, date_marked, present, created_at) VALUES (%s,%s,%s,%s,NOW())",
                    (sid, course_id, date_str, present)
                )

    @staticmethod
    def get_attendance_percentage(student_id, course_id, lookback_days=180):
        # compute cutoff date in Python to avoid interval param issues
        cutoff = (datetime.now() - timedelta(days=int(lookback_days))).date()
        q = """
        SELECT COALESCE(SUM(present),0), COUNT(*)
        FROM Attendance
        WHERE student_id=%s AND course_id=%s AND date_marked >= %s
        """
        data = execute_query(q, (student_id, course_id, cutoff), fetch=True)
        if not data:
            return 0.0
        s, cnt = data[0]
        if cnt == 0:
            return 0.0
        return round((s or 0) / cnt * 100, 2)

    @staticmethod
    def get_course_attendance_for_date(course_id, date_str):
        q = """
        SELECT s.id, s.name,
               COALESCE((SELECT present FROM Attendance a WHERE a.student_id=s.id AND a.course_id=%s AND DATE(a.date_marked)=%s LIMIT 1), 0) as present
        FROM Students s
        JOIN StudentCourses sc ON s.id = sc.student_id
        WHERE sc.course_id = %s
        ORDER BY s.name
        """
        return execute_query(q, (course_id, date_str, course_id), fetch=True)
