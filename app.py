from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import sqlite3
import face_recognition
import numpy as np
import base64
import io
import os
from PIL import Image
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_session'
import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'static/task_files'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
def get_db_connection():
    conn = sqlite3.connect('attendance.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            staff_id TEXT UNIQUE NOT NULL, 
            department TEXT NOT NULL,
            password TEXT NOT NULL,
            status TEXT DEFAULT 'Pending'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            roll_no TEXT UNIQUE,
            email TEXT,
            department TEXT,
            password TEXT,
            face_path TEXT,
            face_encoding BLOB
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'Present',
            UNIQUE(roll_no, date)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT NOT NULL,
            department TEXT NOT NULL,
            question TEXT NOT NULL,
            opt_a TEXT NOT NULL,
            opt_b TEXT NOT NULL,
            opt_c TEXT NOT NULL,
            opt_d TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            date_posted DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS activity_task (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER,
        department TEXT,
        title TEXT,
        description TEXT,
        total_marks INTEGER,
        file_name TEXT,
        task_date TEXT,
        correct_answer TEXT,
        keywords TEXT
            )''')


    cursor.execute('''CREATE TABLE IF NOT EXISTS  activity_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    task_id INTEGER,
    answer TEXT,
    score INTEGER
        )''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no TEXT NOT NULL,
        department TEXT NOT NULL,
        task_id INTEGER NOT NULL,
        selected_option TEXT NOT NULL,
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(roll_no, task_id)
)
''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS activity_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        task_id INTEGER,
        mark INTEGER,
        staff_id INTEGER
    )''')

    conn.commit()
    conn.close()
    
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'acadsync.admin@gmail.com' 
app.config['MAIL_PASSWORD'] = 'swkmtnhzeugxnajc'  
app.config['MAIL_DEFAULT_SENDER'] = ('your-email@gmail.com')

mail = Mail(app)

@app.route('/')
def home():
    return render_template('index.html')


ADMIN_CREDS = {"username": "admin123", "password": "123"}

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_CREDS['username'] and \
           request.form.get('password') == ADMIN_CREDS['password']:
            session['role'] = 'admin'
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    conn = get_db_connection()
    staff = conn.execute("SELECT * FROM staff").fetchall()
    conn.close()
    return render_template('admin_dashboard.html', staff=staff)

@app.route('/admin/global_report')
def admin_report():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    departments = ['CSE', 'ECE', 'MECH']
    dept_names = departments
    dept_stats = []
    dept_scores = []
    total_attendance_sum = 0
    total_days_global = conn.execute("SELECT COUNT(DISTINCT date) FROM attendance").fetchone()[0] or 1

    for dept in departments:
        # Real avg score from student_answers (MCQ tasks)
        score_data = conn.execute("""
            SELECT AVG(score) FROM (
                SELECT sa.roll_no, COUNT(*) as score
                FROM student_answers sa
                JOIN tasks t ON sa.task_id = t.id
                WHERE sa.selected_option = t.correct_option AND sa.department = ?
                GROUP BY sa.roll_no
            )
        """, (dept,)).fetchone()[0]
        avg_score = round(score_data * 10, 1) if score_data else 0

        # Real student count
        student_count = conn.execute(
            "SELECT COUNT(*) FROM students WHERE department=?", (dept,)
        ).fetchone()[0]

        # Real attendance % per dept
        dept_students = conn.execute(
            "SELECT roll_no FROM students WHERE department=?", (dept,)
        ).fetchall()
        if dept_students and total_days_global > 0:
            roll_nos = [s['roll_no'] for s in dept_students]
            placeholders = ','.join('?' * len(roll_nos))
            present_count = conn.execute(
                f"SELECT COUNT(*) FROM attendance WHERE roll_no IN ({placeholders}) AND status='Present'",
                roll_nos
            ).fetchone()[0]
            possible = total_days_global * len(roll_nos)
            dept_att = round((present_count / possible) * 100, 1) if possible else 0
        else:
            dept_att = 0

        total_attendance_sum += dept_att
        dept_scores.append(avg_score)
        dept_stats.append({
            'name': dept,
            'student_count': student_count,
            'avg_score': avg_score,
            'attendance': dept_att
        })

    # Overall stats
    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_tasks    = conn.execute("SELECT COUNT(*) FROM activity_task").fetchone()[0]
    total_staff_verified = conn.execute("SELECT COUNT(*) FROM staff WHERE status='Verified'").fetchone()[0]

    # Overall avg score across all depts
    overall_score_data = conn.execute("""
        SELECT AVG(score) FROM (
            SELECT sa.roll_no, COUNT(*) as score
            FROM student_answers sa
            JOIN tasks t ON sa.task_id = t.id
            WHERE sa.selected_option = t.correct_option
            GROUP BY sa.roll_no
        )
    """).fetchone()[0]
    overall_avg_score = round(overall_score_data * 10, 1) if overall_score_data else 0

    # Monthly attendance trend (last 6 months of data)
    monthly_att = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               COUNT(DISTINCT date) as days,
               COUNT(CASE WHEN status='Present' THEN 1 END) as present_count,
               COUNT(DISTINCT roll_no) as student_count
        FROM attendance
        GROUP BY strftime('%Y-%m', date)
        ORDER BY month DESC
        LIMIT 6
    """).fetchall()
    monthly_att = list(reversed(monthly_att))

    monthly_labels = []
    monthly_values = []
    import calendar
    for row in monthly_att:
        try:
            yr, mo = row['month'].split('-')
            monthly_labels.append(calendar.month_abbr[int(mo)])
            possible = row['days'] * row['student_count']
            pct = round((row['present_count'] / possible) * 100, 1) if possible else 0
            monthly_values.append(pct)
        except Exception:
            pass

    # Task completion per dept
    task_completion = []
    for dept in departments:
        total_t = conn.execute("SELECT COUNT(*) FROM activity_task WHERE department=?", (dept,)).fetchone()[0]
        answered = conn.execute("""
            SELECT COUNT(DISTINCT aa.task_id)
            FROM activity_answers aa
            JOIN activity_task at2 ON aa.task_id = at2.id
            WHERE at2.department=?
        """, (dept,)).fetchone()[0]
        task_completion.append(answered if total_t else 0)

    # Top performers (from activity_answers scores)
    top_performers = conn.execute("""
        SELECT s.name, s.roll_no, s.department,
               COALESCE(SUM(aa.score), 0) as total_score,
               COUNT(aa.task_id) as tasks_done
        FROM students s
        LEFT JOIN activity_answers aa ON aa.student_id = s.roll_no
        GROUP BY s.roll_no
        HAVING tasks_done > 0
        ORDER BY total_score DESC
        LIMIT 5
    """).fetchall()

    conn.close()

    avg_attendance = round(total_attendance_sum / len(departments), 1) if departments else 0

    return render_template('admin_report.html',
        dept_names=dept_names,
        dept_scores=dept_scores,
        dept_stats=dept_stats,
        avg_attendance=avg_attendance,
        total_students=total_students,
        total_tasks=total_tasks,
        total_staff_verified=total_staff_verified,
        overall_avg_score=overall_avg_score,
        monthly_labels=monthly_labels,
        monthly_values=monthly_values,
        task_completion=task_completion,
        top_performers=top_performers
    )

@app.route('/admin/verify/<int:id>')
def verify_staff(id):
    conn = get_db_connection()
    conn.execute("UPDATE staff SET status='Verified' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/staff/register', methods=['GET', 'POST'])
def staff_register():
    if request.method == 'POST':
        name, sid, dept, pwd = request.form['name'], request.form['staff_id'], request.form['department'], request.form['password']
        if not sid.upper().startswith("VIT"):
            return "Error: Staff ID must start with VIT"
        try:
            conn = get_db_connection()
            conn.execute("INSERT INTO staff (name, staff_id, department, password) VALUES (?, ?, ?, ?)", 
                         (name, sid.upper(), dept, pwd))
            conn.commit()
            conn.close()
            return redirect(url_for('staff_login'))
        except: return "Error: Staff ID already registered!"
    return render_template('staff_register.html')



def extract_keywords(text):
    stop_words = {'is', 'the', 'a', 'an', 'and', 'are', 'at', 'for', 'in', 'of', 'on', 'to', 'with', 'approx'}
    
    clean_text = "".join([char.lower() if char.isalnum() or char.isspace() else " " for char in text])
    
    words = clean_text.split()
    keywords = [word for word in words if word not in stop_words and len(word) > 1]
    
    return keywords

@app.route('/staff/add_performance/<int:task_id>', methods=['GET','POST'])
def add_performance(task_id):
    if 'staff_id' not in session:
        return redirect(url_for('staff_login'))

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        mark = request.form.get('mark')
        sid = session.get('staff_id')

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO activity_performance
            (student_id, task_id, mark, staff_id)
            VALUES (?, ?, ?, ?)
        """, (student_id, task_id, mark, sid))

        conn.commit()
        conn.close()

        return redirect(url_for('staff_dashboard'))

    return render_template('add_performance.html')


@app.route('/staff/login', methods=['GET', 'POST'])
def staff_login():
    if request.method == 'POST':
        sid = request.form['staff_id'].upper()
        pwd = request.form['password']

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM staff WHERE staff_id=? AND password=?",
            (sid, pwd)
        ).fetchone()
        conn.close()

        if user:
            if user['status'] == 'Verified':
                session['staff_id'] = sid
                session['staff_name'] = user['name']
                session['staff_dept'] = user['department']   
                return redirect(url_for('staff_dashboard'))
            else:
                return "Account Pending Admin Verification!"

        return "Invalid Staff ID or Password"

    return render_template('staff_login.html')

@app.route('/staff_dashboard')
def staff_dashboard():
    if 'staff_id' not in session: return redirect(url_for('staff_login'))

    dept = session.get('staff_dept')
    conn = get_db_connection()
    from datetime import datetime, timedelta, date
    import calendar

    total_students = conn.execute("SELECT COUNT(*) FROM students WHERE department=?", (dept,)).fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    present_today = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE status='Present' AND date=? AND roll_no IN (SELECT roll_no FROM students WHERE department=?)",
        (today, dept)).fetchone()[0]
    absent_today = total_students - present_today
    total_tasks = conn.execute("SELECT COUNT(*) FROM activity_task WHERE department=?", (dept,)).fetchone()[0]
    total_mcq   = conn.execute("SELECT COUNT(*) FROM tasks WHERE department=?", (dept,)).fetchone()[0]

    weekly_labels, weekly_present, weekly_absent = [], [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        lbl = (datetime.now() - timedelta(days=i)).strftime("%a")
        p = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present' AND roll_no IN (SELECT roll_no FROM students WHERE department=?)",
            (d, dept)).fetchone()[0]
        weekly_labels.append(lbl); weekly_present.append(p)
        weekly_absent.append(max(0, total_students - p))

    monthly_labels, monthly_pct = [], []
    for i in range(5, -1, -1):
        mo_date = datetime.now().replace(day=1)
        for _ in range(i):
            mo_date = (mo_date - timedelta(days=1)).replace(day=1)
        mo_str = mo_date.strftime("%Y-%m")
        mo_lbl = calendar.month_abbr[mo_date.month]
        days_in_mo = conn.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE strftime('%Y-%m',date)=?", (mo_str,)).fetchone()[0]
        present_mo = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE strftime('%Y-%m',date)=? AND status='Present' AND roll_no IN (SELECT roll_no FROM students WHERE department=?)",
            (mo_str, dept)).fetchone()[0]
        possible = days_in_mo * total_students if days_in_mo and total_students else 1
        pct = round((present_mo / possible) * 100, 1) if possible else 0
        monthly_labels.append(mo_lbl); monthly_pct.append(pct)

    score_ranges = {'0-25': 0, '26-50': 0, '51-75': 0, '76-100': 0}
    scores = conn.execute(
        "SELECT SUM(score) as total FROM activity_answers WHERE student_id IN (SELECT roll_no FROM students WHERE department=?) GROUP BY student_id",
        (dept,)).fetchall()
    for row in scores:
        s = row['total'] or 0
        if s <= 25: score_ranges['0-25'] += 1
        elif s <= 50: score_ranges['26-50'] += 1
        elif s <= 75: score_ranges['51-75'] += 1
        else: score_ranges['76-100'] += 1

    top_students = conn.execute(
        "SELECT s.name, s.roll_no, COALESCE(SUM(aa.score),0) as total_score FROM students s LEFT JOIN activity_answers aa ON aa.student_id = s.roll_no WHERE s.department=? GROUP BY s.roll_no ORDER BY total_score DESC LIMIT 5",
        (dept,)).fetchall()

    conn.close()
    return render_template('staff_dashboard.html',
        total_students=total_students, present_today=present_today, absent_today=absent_today,
        total_tasks=total_tasks, total_mcq=total_mcq,
        weekly_labels=weekly_labels, weekly_present=weekly_present, weekly_absent=weekly_absent,
        monthly_labels=monthly_labels, monthly_pct=monthly_pct,
        score_dist=list(score_ranges.values()), score_labels=list(score_ranges.keys()),
        top_students=top_students, today=today)

from datetime import datetime

@app.route('/staff/view_attendance')
def staff_view_attendance():

    if 'staff_id' not in session:
        return redirect(url_for('staff_login'))

    staff_dept = session.get('staff_dept')
    today_date = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()

    query = """
        SELECT 
            s.name,
            s.roll_no,
            s.department,
            COALESCE(a.time, '---') as time,
            COALESCE(a.status, 'Absent') as status
        FROM students s
        LEFT JOIN attendance a
            ON s.roll_no = a.roll_no AND a.date = ?
        WHERE s.department = ?
        ORDER BY s.roll_no
    """

    students = conn.execute(query, (today_date, staff_dept)).fetchall()
    conn.close()

    return render_template(
        'staff_attendance_view.html',
        students=students,
        date=today_date,
        department=staff_dept
    )

@app.route('/staff/add_student')
def add_student_page():
    return render_template("add_student.html")

@app.route('/staff/upload_task', methods=['GET', 'POST'])
def upload_task():

    if 'staff_id' not in session:
        return redirect(url_for('staff_login'))

    if request.method == 'POST':

        title = request.form.get('title')
        description = request.form.get('description')
        marks = request.form.get('total_marks')
        correct_answer = request.form.get('correct_answer')
        date = request.form.get('task_date')

        file = request.files['task_file']
        filename = ""

        if file and file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        dept = session.get('staff_dept')
        staff_id = session.get('staff_id')

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO activity_task
            (staff_id, department, title, description, total_marks, file_name, correct_answer, task_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (staff_id, dept, title, description, marks, filename, correct_answer, date))

        conn.commit()
        conn.close()

        return redirect(url_for('staff_dashboard'))

    return render_template('upload_task.html')

@app.route('/staff/add_activity_task', methods=['GET', 'POST'])
def add_activity_task():
    if 'staff_id' not in session:
        return redirect(url_for('staff_login'))

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        marks = request.form.get('total_marks')
        date = request.form.get('task_date')

        dept = session.get('staff_dept')
        sid = session.get('staff_id')

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO activity_tasks
            (staff_id, department, task_title, task_description, total_marks, task_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (sid, dept, title, description, marks, date))

        conn.commit()
        conn.close()

        return redirect(url_for('staff_dashboard'))

    return render_template('add_activity_task.html')

@app.route('/register_face', methods=['POST'])
def register_face():
    try:
        data = request.get_json()

        if not data:
            return "No data received", 400
        name = data.get('name')
        roll_no = data.get('roll_no')
        email = data.get('email')
        dept = data.get('dept')
        password = data.get('password')
        image_data = data.get('image')

        if not all([name, roll_no, email, dept, password, image_data]):
            return "Missing student details", 400
        if "," in image_data:
            image_data = image_data.split(",")[1]

        img_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)
        encodings = face_recognition.face_encodings(img_np)

        if len(encodings) == 0:
            return "No face detected. Please look straight at the camera.", 400

        face_encoding_blob = encodings[0].tobytes()
        if not os.path.exists("static/faces"):
            os.makedirs("static/faces")

        file_path = f"static/faces/{roll_no}.jpg"
        img.save(file_path, "JPEG")
        conn = get_db_connection()
        existing = conn.execute(
            "SELECT * FROM students WHERE roll_no=? OR email=?",
            (roll_no, email)
        ).fetchone()

        if existing:
            conn.close()
            return "Student already exists!", 400

        conn.execute("""
            INSERT INTO students
            (name, roll_no, email, department, password, face_path, face_encoding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, roll_no, email, dept, password, file_path, face_encoding_blob))

        conn.commit()
        conn.close()
        msg = Message(
            "Veera Technology College | Your Student Account is Activated",
            recipients=[email]
        )

        msg.html = f"""
        <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 650px; margin: auto; border-radius: 18px; overflow: hidden; box-shadow: 0 8px 25px rgba(0,0,0,0.08); border: 1px solid #eee;">

            <div style="background: linear-gradient(135deg, #ff9900, #f26522); padding: 35px; text-align: center; color: white;">
                <h1 style="margin: 0;">Veera Technology College</h1>
                <p style="margin: 5px 0 0;">Official Student Account Information</p>
            </div>

            <div style="padding: 35px; color: #333;">
                <h2 style="color: #f26522;">Hello {name},</h2>

                <p>
                Your student portal account has been created by the college administration under the
                <strong>{dept}</strong> department.
                Your Face ID is securely registered in our smart attendance system.
                </p>

                <div style="background: #fff7ed; border-left: 6px solid #ff9900; padding: 20px; margin: 25px 0; border-radius: 8px;">
                    <p><strong>Roll Number:</strong> {roll_no}</p>
                    <p><strong>Email:</strong> {email}</p>
                    <p><strong>Password:</strong> {password}</p>
                </div>

                <div style="background: linear-gradient(135deg,#fff3e0,#ffe0cc); padding:20px; border-radius:12px;">
                    <b>🎓 Motivation for You</b>
                    <p style="margin-top:10px;">
                    Every expert was once a beginner. Your college journey starts today.
                    Attend regularly, learn consistently, and build your future with confidence.
                    Success is not luck — it is discipline and dedication.
                    </p>
                </div>

                <div style="text-align:center;margin-top:35px;">
                    <a href="http://127.0.0.1:2745/student/login"
                    style="background:linear-gradient(to right,#ff9900,#f26522);
                    color:white;padding:14px 30px;text-decoration:none;border-radius:30px;
                    font-weight:bold;display:inline-block;">
                    Login to Student Portal
                    </a>
                </div>

                <p style="font-size:13px;color:#777;margin-top:25px;">
                Please change your password after first login for security.
                </p>
            </div>

            <div style="background:#f8f9fa;padding:18px;text-align:center;font-size:12px;color:#888;">
            © 2026 Veera Technology College • Automated Mail
            </div>
        </div>
        """

        mail.send(msg)

        return "Student added successfully and email sent!"

    except Exception as e:
        print("REGISTER FACE ERROR:", e)
        return f"Server Error: {str(e)}", 500

    
@app.route('/student/login')
def student_login_page():
    return render_template("student_login.html")

@app.route('/face_login', methods=['POST'])
def face_login():
    try:
        data = request.get_json(force=True)
        email = data.get('email')
        password = data.get('password')
        image_data = data.get('image')

        if not email or not password or not image_data:
            return jsonify({"status":"fail","message":"Missing login details"})

        image_data = image_data.split(",")[1]
        img_bytes = base64.b64decode(image_data)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img_np = np.array(img)

        unknown_encodings = face_recognition.face_encodings(img_np)
        if len(unknown_encodings) == 0:
            return jsonify({"status":"fail","message":"No face detected."})

        live_encoding = unknown_encodings[0]

        conn = get_db_connection()
        student = conn.execute("SELECT * FROM students WHERE email=? AND password=?", (email, password)).fetchone()

        if not student:
            conn.close()
            return jsonify({"status":"fail","message":"Invalid Credentials"})

        stored_encoding = np.frombuffer(student['face_encoding'], dtype=np.float64)
        match = face_recognition.compare_faces([stored_encoding], live_encoding)

        if match[0]:
            now = datetime.now()
            today_date = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%I:%M %p")
            try:
                conn.execute(
                    "INSERT INTO attendance (roll_no, name, date, time, status) VALUES (?, ?, ?, ?, ?)",
                    (student['roll_no'], student['name'], today_date, current_time, 'Present')
                )
                conn.commit()
                message = "Login Successful! Your attendance has been marked for today."
            except sqlite3.IntegrityError:
                message = "Login Successful! (Attendance already recorded earlier today)"
            
            session['student'] = student['roll_no']
            session['student_name'] = student['name']
            session['student_dept'] = student['department']
            session['roll_no'] = student['roll_no']  
            conn.close()
            return jsonify({"status":"success", "message": message})
        else:
            conn.close()
            return jsonify({"status":"fail", "message":"Face not matching"})

    except Exception as e:
        print("FACE LOGIN ERROR:", e)
        return jsonify({"status":"error", "message": str(e)})
    
@app.route('/student/dashboard')
def student_dashboard():
    if 'student' not in session:
        redirect(url_for('face_login'))
    
    return render_template('student_dashboard.html')


@app.route('/student/tasks')
def student_tasks():
    if 'student' not in session:
        return redirect(url_for('student_login_page'))

    student_id = session.get('student')
    dept = session.get('student_dept')

    conn = get_db_connection()
    
    query = """
        SELECT * FROM activity_task 
        WHERE department = ? 
        AND id NOT IN (
            SELECT task_id FROM activity_answers WHERE student_id = ?
        )
    """
    
    tasks = conn.execute(query, (dept, student_id)).fetchall()
    conn.close()

    return render_template('student_tasks.html', tasks=tasks)

@app.route('/student/submit_answer/<int:task_id>', methods=['POST'])
def submit_answer(task_id):
    if 'student' not in session:
        return redirect(url_for('student_login'))

    student_id = session.get('student')
    student_ans_raw = request.form.get('answer', '').strip()
    
    student_ans_lower = student_ans_raw.lower()

    conn = get_db_connection()

    existing = conn.execute("SELECT id FROM activity_answers WHERE student_id = ? AND task_id = ?", 
                          (student_id, task_id)).fetchone()
    if existing:
        conn.close()
        return "Submission blocked: You have already completed this task.", 403

    task = conn.execute("SELECT correct_answer, total_marks FROM activity_task WHERE id=?", 
                        (task_id,)).fetchone()

    if task is None:
        conn.close()
        return f"Error: Task with ID {task_id} not found.", 404

    original_correct = task['correct_answer']
    total_marks = float(task['total_marks'])

    # 3. AUTOMATIC SCORING
    score = 0
    
    # Full Marks: Exact Match
    if student_ans_lower == original_correct.lower().strip():
        score = total_marks
    else:
        # Partial Marks: Check keywords automatically extracted
        auto_keywords = extract_keywords(original_correct)
        
        match_count = 0
        for word in auto_keywords:
            if word in student_ans_lower:
                match_count += 1
        
        # If any keyword matches, give half marks
        if match_count > 0:
            score = total_marks / 2

    # 4. Save and Finish
    conn.execute("INSERT INTO activity_answers (student_id, task_id, answer, score) VALUES (?, ?, ?, ?)",
                 (student_id, task_id, student_ans_raw, score))
    conn.commit()
    conn.close()

    return redirect(url_for('student_dashboard'))

@app.route('/student/view_scores')
def view_scores():
    # 1. Security Check
    if 'student' not in session:
        return redirect(url_for('student_login'))

    student_id = session.get('student')
    print(student_id)
    conn = get_db_connection()

    # 2. Dynamic Query
    # We join activity_tasks (t) and activity_answers (a) 
    # to get both the student's work and the original task details
    query = """
        SELECT 
            t.title, 
            t.task_date, 
            t.correct_answer, 
            t.total_marks, 
            a.answer, 
            a.score
        FROM activity_answers a
        JOIN activity_task t ON a.task_id = t.id
        WHERE a.student_id = ?
        ORDER BY t.task_date DESC
    """
    
    results = conn.execute(query, (student_id,)).fetchall()

    # 3. Calculate Cumulative Total
    # This sums up all scores for the "Performance Header" in your HTML
    total_score = sum(row['score'] for row in results) if results else 0

    conn.close()

    # 4. Render the Full Template
    return render_template(
        'view_score.html', 
        results=results, 
        total=total_score
    )

@app.route('/student/view_attendance')
def student_view_attendance():

    if 'roll_no' not in session:
        return redirect('/student/login')

    roll_no = session['roll_no']

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance")
    total_days = cursor.fetchone()[0]
    cursor.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE roll_no=? AND status='Present'
    """, (roll_no,))
    attended_days = cursor.fetchone()[0]

    conn.close()
    if total_days == 0:
        percentage = 0
    else:
        percentage = round((attended_days / total_days) * 100, 2)

    return render_template(
        'student_attendance.html',
        total_days=total_days,
        attended_days=attended_days,
        percentage=percentage
    )

@app.route('/staff/view_scores')
def staff_view_scores():

    if 'staff_id' not in session:
        return redirect(url_for('staff_login'))

    staff_dept = session.get('staff_dept')
    print(staff_dept)

    conn = get_db_connection()

    # Get only staff department students
    students = conn.execute(
        "SELECT id, name, roll_no FROM students WHERE department=?",
        (staff_dept,)
    ).fetchall()
    print('students',students)

    student_results = []

    for student in students:
        print(student['id'])

        result = conn.execute("""
            SELECT 
                COUNT(task_id) as total_tasks,
                COALESCE(SUM(score),0) as total_score
            FROM activity_answers
            WHERE student_id = ?
        """, (student['roll_no'],)).fetchone()

        if result['total_tasks'] == 0:
            status = "Not Attended"
        else:
            status = "Attended"

        student_results.append({
            'name': student['name'],
            'roll_no': student['roll_no'],
            'status': status,
            'score': result['total_score'],
            'total_tasks': result['total_tasks']
        })

    conn.close()
    print(student_results)

    return render_template(
        'staff_view_scores.html',
        results=student_results,
        dept=staff_dept
    )


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
