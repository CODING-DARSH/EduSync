from datetime import datetime, timedelta
import random
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv
from twilio.rest import Client
from db import execute_query

# Load environment variables
load_dotenv()


# ---------------- OTP / EMAIL / SMS UTILITIES ----------------
def send_email_otp(email, otp):
    """Send OTP via Gmail (uses env vars EMAIL_ADDR and EMAIL_APP_PASSWORD)."""
    sender = os.getenv("EMAIL_ADDR") or "yourapp@gmail.com"
    app_password = os.getenv("EMAIL_APP_PASSWORD")

    msg = MIMEText(f"Your Student Portal OTP is: {otp}")
    msg["Subject"] = "Student Portal Login OTP"
    msg["From"] = sender
    msg["To"] = email

    if not app_password:
        print("❗ EMAIL_APP_PASSWORD not set — skipping real email send (dev mode).")
        print(f"📧 [DEV MODE] OTP for {email}: {otp}")
        return

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, app_password)
            server.send_message(msg)
        print(f"✅ OTP sent to email: {email}")
    except Exception as e:
        print(f"❌ Email send error: {e}")


def send_sms_otp(phone, otp):
    """Send OTP via Twilio (prints in dev mode if Twilio not configured)."""
    print(f"📱 [DEV MODE] OTP to {phone}: {otp}")

    sid = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not (sid and token and from_number):
        print("❗ Twilio creds not set — skipping real SMS send (dev mode).")
        return

    try:
        client = Client(sid, token)
        client.messages.create(
            body=f"Your Student Portal OTP is {otp}",
            from_=from_number,
            to=f"+91{phone}" if not phone.startswith("+") else phone,
        )
        print(f"✅ OTP sent to phone: {phone}")
    except Exception as e:
        print(f"❌ SMS send error: {e}")


# ---------------- STUDENT MODEL ----------------
class Student:
    @staticmethod
    def change_password(student_id, old_password, new_password):
        q = "SELECT password FROM Students WHERE id=:1"
        data = execute_query(q, (student_id,), fetch=True)
        if data and data[0][0] == old_password:
            execute_query("UPDATE Students SET password=:1 WHERE id=:2", (new_password, student_id))
            return True
        return False

    @staticmethod
    def get_course_grades(student_id):
        q = """
        SELECT c.course_name, sc.marks
        FROM Courses c
        JOIN StudentCourses sc ON c.id = sc.course_id
        WHERE sc.student_id = :1
        """
        data = execute_query(q, (student_id,), fetch=True)
        return [(row[0], row[1] or 0) for row in data]

    @staticmethod
    def export_csv(student_id):
        data = execute_query("""
            SELECT c.course_name, sc.marks
            FROM Courses c
            JOIN StudentCourses sc ON c.id = sc.course_id
            WHERE sc.student_id = :1
        """, (student_id,), fetch=True)

        filename = f"student_{student_id}_report.csv"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("Course,Marks\n")
                for d in data:
                    f.write(f"{d[0]},{d[1] or 'N/A'}\n")
            print(f"✅ Exported report to {filename}")
        except Exception as e:
            print(f"❌ Failed to write CSV: {e}")

    @staticmethod
    def get_notifications(student_id):
        try:
            q = "SELECT message, created_at FROM Notifications WHERE student_id=:1 ORDER BY created_at DESC"
            return execute_query(q, (student_id,), fetch=True)
        except Exception:
            return []

    @staticmethod
    def get_details(student_id):
        q = "SELECT id, name, grades FROM Students WHERE id=:1"
        data = execute_query(q, (int(student_id),), fetch=True)
        return data[0] if data else None

    @staticmethod
    def register(name, email, phone, password):
        next_id = execute_query("SELECT NVL(MAX(id), 0) + 1 FROM Students", fetch=True)[0][0]
        execute_query(
            "INSERT INTO Students (id, name, email, phone, password) VALUES (:1, :2, :3, :4, :5)",
            (next_id, name, email, phone, password),
        )
        print(f"✅ Student registered successfully with ID: {next_id}")
        return next_id

    @staticmethod
    def login(student_id, password):
        q = "SELECT id, name FROM Students WHERE id=:1 AND password=:2"
        data = execute_query(q, (student_id, password), fetch=True)
        return data[0] if data else None

    @staticmethod
    def enroll(student_id, course_id):
        execute_query("INSERT INTO StudentCourses (student_id, course_id) VALUES (:1, :2)", (student_id, course_id))

    @staticmethod
    def show_courses(student_id):
        q = """
        SELECT c.course_name
        FROM Courses c
        JOIN StudentCourses sc ON c.id = sc.course_id
        WHERE sc.student_id = :1
        """
        data = execute_query(q, (student_id,), fetch=True)
        return [row[0] for row in data]


# ---------------- TEACHER MODEL ----------------
class Teacher:
    @staticmethod
    def grade_submission(submission_id, marks):
        """Grade a submission and update student's course average."""
        execute_query("UPDATE Submissions SET marks=:1 WHERE id=:2", (marks, submission_id))

        # Get student_id and course_id
        data = execute_query("""
            SELECT s.student_id, a.course_id
            FROM Submissions s
            JOIN Assignments a ON s.assignment_id = a.id
            WHERE s.id = :1
        """, (submission_id,), fetch=True)

        if not data:
            print("❌ Could not find related student/course for submission.")
            return

        student_id, course_id = data[0]

        # Update StudentCourses with average marks
        execute_query("""
            UPDATE StudentCourses SET marks = (
                SELECT ROUND(AVG(s.marks), 2)
                FROM Submissions s
                JOIN Assignments a ON s.assignment_id = a.id
                WHERE s.student_id = :1 AND a.course_id = :2 AND s.marks IS NOT NULL
            )
            WHERE student_id = :1 AND course_id = :2
        """, (student_id, course_id))

        print(f"✅ Updated average marks for Student {student_id} in Course {course_id}")

    @staticmethod
    def register(name, password):
        next_id = execute_query("SELECT NVL(MAX(id), 0) + 1 FROM Teachers", fetch=True)[0][0]
        execute_query("INSERT INTO Teachers (id, name, password) VALUES (:1, :2, :3)", (next_id, name, password))
        print(f"✅ Teacher registered successfully with ID: {next_id}")
        return next_id

    @staticmethod
    def login(teacher_id, password):
        q = "SELECT id, name FROM Teachers WHERE id=:1 AND password=:2"
        data = execute_query(q, (teacher_id, password), fetch=True)
        return data[0] if data else None

    @staticmethod
    def assign_grade(teacher_id, student_id, course_id, marks):
        q = "SELECT id FROM Courses WHERE id=:1 AND teacher_id=:2"
        data = execute_query(q, (course_id, teacher_id), fetch=True)
        if not data:
            print("❌ Unauthorized: teacher not assigned to this course.")
            return False
        execute_query("UPDATE StudentCourses SET marks=:1 WHERE student_id=:2 AND course_id=:3",
                      (marks, student_id, course_id))
        print(f"✅ Marks updated for student {student_id} in course {course_id}")
        return True

    @staticmethod
    def assign_to_course(teacher_id, course_id):
        next_id = execute_query("SELECT NVL(MAX(id), 0) + 1 FROM TeacherCourses", fetch=True)[0][0]
        execute_query("INSERT INTO TeacherCourses (id, teacher_id, course_id) VALUES (:1, :2, :3)",
                      (next_id, teacher_id, course_id))
        return True

    @staticmethod
    def get_courses(teacher_id):
        q = """SELECT c.id, c.course_name 
               FROM Courses c
               JOIN TeacherCourses tc ON c.id = tc.course_id
               WHERE tc.teacher_id = :1"""
        return execute_query(q, (teacher_id,), fetch=True)


# ---------------- ADMIN MODEL ----------------
class Admin:
    @staticmethod
    def login(username, password):
        q = "SELECT username FROM Admins WHERE username=:1 AND password=:2"
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
        otp_code = str(random.randint(100000, 999999))
        expires_at = datetime.now() + timedelta(minutes=5)
        next_id = execute_query("SELECT NVL(MAX(id), 0) + 1 FROM OTP_CODES", fetch=True)[0][0]
        execute_query("INSERT INTO OTP_CODES (id, student_id, otp_code, expires_at) VALUES (:1, :2, :3, :4)",
                      (next_id, student_id, otp_code, expires_at))
        print(f"✅ OTP {otp_code} generated for student_id {student_id}")
        return otp_code

    @staticmethod
    def verify_otp(student_id, otp_code):
        q = """SELECT otp_code, expires_at 
               FROM OTP_CODES 
               WHERE student_id=:1 ORDER BY expires_at DESC"""
        data = execute_query(q, (student_id,), fetch=True)
        if not data:
            return False
        otp, expiry = data[0]
        return otp == otp_code and datetime.now() < expiry


# ---------------- ASSIGNMENT + SUBMISSION MODELS ----------------
class Assignment:
    @staticmethod
    def create(course_id, teacher_id, title, description, due_date):
        next_id = execute_query("SELECT NVL(MAX(id), 0)+1 FROM Assignments", fetch=True)[0][0]
        execute_query("""INSERT INTO Assignments (id, course_id, teacher_id, title, description, due_date)
                         VALUES (:1, :2, :3, :4, :5, :6)""",
                      (next_id, course_id, teacher_id, title, description, due_date))
        return next_id

    @staticmethod
    def get_for_teacher(teacher_id):
        q = "SELECT id, title, description, due_date FROM Assignments WHERE teacher_id=:1"
        return execute_query(q, (teacher_id,), fetch=True)


class Submission:
    @staticmethod
    def submit(assignment_id, student_id, file_path):
        next_id = execute_query("SELECT NVL(MAX(id), 0) + 1 FROM Submissions", fetch=True)[0][0]
        execute_query("""INSERT INTO Submissions (id, assignment_id, student_id, file_path)
                         VALUES (:1, :2, :3, :4)""",
                      (next_id, assignment_id, student_id, file_path))
        return next_id

    @staticmethod
    def get_for_student(student_id):
        q = """SELECT a.title, s.file_path, s.submitted_at, s.marks
               FROM Submissions s
               JOIN Assignments a ON s.assignment_id = a.id
               WHERE s.student_id = :1"""
        return execute_query(q, (student_id,), fetch=True)

