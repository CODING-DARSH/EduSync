from flask import Flask, render_template, request, redirect, session, jsonify
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from models import Student, Teacher, Admin


app = Flask(__name__)
app.secret_key = "secretkey123"

# ---------- ROUTES ----------
@app.route('/')
def home():
    return render_template('login.html')

@app.route('/student/login', methods=['POST'])
def student_login():
    student_id = request.form['id']
    password = request.form['password']
    user = Student.login(student_id, password)
    if user:
        session['student_id'] = user[0]
        return redirect('/student/dashboard')
    return "Invalid credentials"

@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect('/')
    courses = Student.show_courses(session['student_id'])
    return render_template('student_dashboard.html', courses=courses)

@app.route('/student/enroll', methods=['POST'])
def enroll():
    if 'student_id' not in session:
        return "Not logged in"
    course_id = request.form['course_id']
    Student.enroll(session['student_id'], course_id)
    return redirect('/student/dashboard')

@app.route('/teacher/grade', methods=['POST'])
def assign_grade():
    student_id = request.form['student_id']
    grade = request.form['grade']
    Teacher.assign_grade(student_id, grade)
    return jsonify({"message": "Grade assigned"})

@app.route('/admin/login', methods=['POST'])
def admin_login():
    username = request.form['username']
    password = request.form['password']
    if Admin.login(username, password):
        session['admin'] = username
        return redirect('/admin/dashboard')
    return "Invalid admin credentials"

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect('/')
    students = Admin.show_all_students()
    return render_template('admin_dashboard.html', students=students)

if __name__ == '__main__':
    app.run(debug=True)
