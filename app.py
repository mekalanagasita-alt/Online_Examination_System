import sqlite3
conn = sqlite3.connect("exam.db", check_same_thread=False)


from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# MongoDB Configuration
client = MongoClient('mongodb://localhost:27017/')
db = client.exam_system
users_collection = db.users
exams_collection = db.exams
results_collection = db.results

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = users_collection.find_one({'email': email})
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form.get('role', 'student')
        
        # Check if user already exists
        if users_collection.find_one({'email': email}):
            flash('Email already registered', 'error')
            return render_template('register.html')
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user_data = {
            'username': username,
            'email': email,
            'password': hashed_password,
            'role': role,
            'created_at': datetime.now()
        }
        
        result = users_collection.insert_one(user_data)
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    
    # Get available exams
    exams = list(exams_collection.find({'is_active': True}))
    
    # Get user's recent results
    user_results = list(results_collection.find({'student_id': ObjectId(session['user_id'])}).sort('completed_at', -1).limit(5))
    
    # Add exam titles to results
    for result in user_results:
        exam = exams_collection.find_one({'_id': result['exam_id']})
        result['exam_title'] = exam['title'] if exam else 'Unknown Exam'
    
    return render_template('dashboard.html', exams=exams, recent_results=user_results)

@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # Get statistics
    total_exams = exams_collection.count_documents({})
    total_students = users_collection.count_documents({'role': 'student'})
    total_results = results_collection.count_documents({})
    active_exams = exams_collection.count_documents({'is_active': True})
    
    # Get recent exams
    recent_exams = list(exams_collection.find().sort('created_at', -1).limit(5))
    
    stats = {
        'total_exams': total_exams,
        'total_students': total_students,
        'total_results': total_results,
        'active_exams': active_exams
    }
    
    return render_template('admin_dashboard.html', stats=stats, recent_exams=recent_exams)

@app.route('/admin/create-exam', methods=['GET', 'POST'])
@admin_required
def create_exam():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        duration = int(request.form['duration'])
        
        # Get questions from form
        questions = []
        question_count = int(request.form['question_count'])
        
        for i in range(question_count):
            question_text = request.form[f'question_{i}']
            options = [
                request.form[f'option_{i}_0'],
                request.form[f'option_{i}_1'],
                request.form[f'option_{i}_2'],
                request.form[f'option_{i}_3']
            ]
            correct_answer = int(request.form[f'correct_answer_{i}'])
            
            questions.append({
                'question': question_text,
                'options': options,
                'correct_answer': correct_answer
            })
        
        exam_data = {
            'title': title,
            'description': description,
            'duration': duration,
            'questions': questions,
            'created_by': ObjectId(session['user_id']),
            'created_at': datetime.now(),
            'is_active': True
        }
        
        exams_collection.insert_one(exam_data)
        flash('Exam created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    return render_template('create_exam.html')

@app.route('/admin/exams')
@admin_required
def admin_exams():
    exams = list(exams_collection.find().sort('created_at', -1))
    return render_template('admin_exams.html', exams=exams)

@app.route('/admin/toggle-exam/<exam_id>')
@admin_required
def toggle_exam_status(exam_id):
    exam = exams_collection.find_one({'_id': ObjectId(exam_id)})
    if exam:
        new_status = not exam['is_active']
        exams_collection.update_one(
            {'_id': ObjectId(exam_id)},
            {'$set': {'is_active': new_status}}
        )
        status_text = 'activated' if new_status else 'deactivated'
        flash(f'Exam {status_text} successfully!', 'success')
    return redirect(url_for('admin_exams'))

@app.route('/exam/<exam_id>')
@login_required
def take_exam(exam_id):
    # Check if user already took this exam
    existing_result = results_collection.find_one({
        'student_id': ObjectId(session['user_id']),
        'exam_id': ObjectId(exam_id)
    })
    
    if existing_result:
        flash('You have already taken this exam', 'info')
        return redirect(url_for('view_result', exam_id=exam_id))
    
    exam = exams_collection.find_one({'_id': ObjectId(exam_id)})
    if not exam or not exam['is_active']:
        flash('Exam not available', 'error')
        return redirect(url_for('dashboard'))
    
    return render_template('take_exam.html', exam=exam)

@app.route('/submit-exam', methods=['POST'])
@login_required
def submit_exam():
    exam_id = request.form['exam_id']
    exam = exams_collection.find_one({'_id': ObjectId(exam_id)})
    
    if not exam:
        return jsonify({'error': 'Exam not found'}), 404
    
    # Get user answers
    answers = []
    score = 0
    
    for i, question in enumerate(exam['questions']):
        user_answer = request.form.get(f'question_{i}')
        if user_answer:
            user_answer = int(user_answer)
            answers.append(user_answer)
            if user_answer == question['correct_answer']:
                score += 1
        else:
            answers.append(-1)  # No answer selected
    
    # Calculate percentage
    total_questions = len(exam['questions'])
    percentage = (score / total_questions) * 100 if total_questions > 0 else 0
    
    # Save result
    result_data = {
        'student_id': ObjectId(session['user_id']),
        'exam_id': ObjectId(exam_id),
        'answers': answers,
        'score': score,
        'total_questions': total_questions,
        'percentage': percentage,
        'completed_at': datetime.now(),
        'time_taken': int(request.form.get('time_taken', 0))
    }
    
    result_id = results_collection.insert_one(result_data).inserted_id
    return redirect(url_for('view_result', exam_id=exam_id))

@app.route('/results/<exam_id>')
@login_required
def view_result(exam_id):
    result = results_collection.find_one({
        'student_id': ObjectId(session['user_id']),
        'exam_id': ObjectId(exam_id)
    })
    
    if not result:
        flash('Result not found', 'error')
        return redirect(url_for('dashboard'))
    
    exam = exams_collection.find_one({'_id': ObjectId(exam_id)})
    
    # Prepare detailed results
    detailed_results = []
    for i, question in enumerate(exam['questions']):
        user_answer = result['answers'][i] if i < len(result['answers']) else -1
        detailed_results.append({
            'question': question['question'],
            'options': question['options'],
            'correct_answer': question['correct_answer'],
            'user_answer': user_answer,
            'is_correct': user_answer == question['correct_answer']
        })
    
    return render_template('results.html', result=result, exam=exam, detailed_results=detailed_results)

@app.route('/admin/results')
@admin_required
def admin_results():
    # Get all results with student and exam info
    results = list(results_collection.find().sort('completed_at', -1))
    
    for result in results:
        # Get student info
        student = users_collection.find_one({'_id': result['student_id']})
        result['student_name'] = student['username'] if student else 'Unknown'
        
        # Get exam info
        exam = exams_collection.find_one({'_id': result['exam_id']})
        result['exam_title'] = exam['title'] if exam else 'Unknown'
    
    return render_template('admin_results.html', results=results)

# Initialize sample data
def init_sample_data():
    # Create admin user if doesn't exist
    if not users_collection.find_one({'email': 'admin@test.com'}):
        admin_user = {
            'username': 'Admin',
            'email': 'admin@test.com',
            'password': generate_password_hash('password123'),
            'role': 'admin',
            'created_at': datetime.now()
        }
        users_collection.insert_one(admin_user)
        print("Admin user created: admin@test.com / password123")
    
    # Create sample student if doesn't exist
    if not users_collection.find_one({'email': 'student@test.com'}):
        student_user = {
            'username': 'Student',
            'email': 'student@test.com',
            'password': generate_password_hash('password123'),
            'role': 'student',
            'created_at': datetime.now()
        }
        users_collection.insert_one(student_user)
        print("Student user created: student@test.com / password123")
    
    # Create sample exam if doesn't exist
    if exams_collection.count_documents({}) == 0:
        sample_exam = {
            'title': 'Python Basics Quiz',
            'description': 'Test your knowledge of Python programming basics',
            'duration': 30,
            'questions': [
                {
                    'question': 'What is the correct way to create a list in Python?',
                    'options': ['list = []', 'list = ()', 'list = {}', 'list = ""'],
                    'correct_answer': 0
                },
                {
                    'question': 'Which keyword is used to define a function in Python?',
                    'options': ['function', 'def', 'define', 'func'],
                    'correct_answer': 1
                },
                {
                    'question': 'What does "len()" function do in Python?',
                    'options': ['Returns length of object', 'Returns type of object', 'Returns value of object', 'Returns name of object'],
                    'correct_answer': 0
                },
                {
                    'question': 'Which of the following is a mutable data type in Python?',
                    'options': ['tuple', 'string', 'list', 'int'],
                    'correct_answer': 2
                },
                {
                    'question': 'What is the output of print(2 ** 3) in Python?',
                    'options': ['6', '8', '9', '5'],
                    'correct_answer': 1
                }
            ],
            'created_by': users_collection.find_one({'role': 'admin'})['_id'],
            'created_at': datetime.now(),
            'is_active': True
        }
        exams_collection.insert_one(sample_exam)
        print("Sample exam created: Python Basics Quiz")

if __name__ == "__main__":
    app.run()
