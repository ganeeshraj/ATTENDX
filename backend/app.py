import os, math, secrets
from datetime import datetime, date, time as dtime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, '..', 'frontend'), static_url_path='')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
db_url = os.getenv('DATABASE_URL')
# Render/PostgreSQL compatibility: SQLAlchemy + psycopg 3
if db_url and db_url.startswith('postgres://'):
    db_url = 'postgresql+psycopg://' + db_url[len('postgres://'):]
elif db_url and db_url.startswith('postgresql://'):
    db_url = 'postgresql+psycopg://' + db_url[len('postgresql://'):]
if not db_url and os.getenv('DB_HOST'):
    db_user = os.getenv('DB_USER', 'root')
    db_pass = os.getenv('DB_PASSWORD', '')
    db_host = os.getenv('DB_HOST', '127.0.0.1')
    db_port = os.getenv('DB_PORT', '3306')
    db_name = os.getenv('DB_NAME', 'attendx')
    from urllib.parse import quote_plus
    db_url = f'mysql+pymysql://{quote_plus(db_user)}:{quote_plus(db_pass)}@{db_host}:{db_port}/{db_name}'
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///' + os.path.join(BASE, 'attendx.db')
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# AttendX uses India Standard Time (IST) for attendance rules.
# This prevents a UTC/local-machine timezone mismatch from rejecting
# attendance even when the phone shows the correct Indian time.
ATTENDX_TZ = ZoneInfo('Asia/Kolkata')

def local_now():
    return datetime.now(ATTENDX_TZ)

def local_today():
    return local_now().date()

LATE_AFTER_MINUTES, RADIUS = 15, 100
DEV = os.getenv('DEV_IGNORE_TIME') == '1'

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login_id = db.Column(db.String(30), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # student | faculty | principal
    department = db.Column(db.String(60), default='')
    year = db.Column(db.String(10), default='')

class AttSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    subject = db.Column(db.String(80), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    day = db.Column(db.Date, default=local_today)
    created_at = db.Column(db.DateTime, default=lambda: local_now().replace(tzinfo=None))
    close_at = db.Column(db.Time, nullable=True)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('att_session.id'), nullable=False)
    subject = db.Column(db.String(80))
    day = db.Column(db.Date)
    at = db.Column(db.Time)
    status = db.Column(db.String(10), default='Absent')
    marked = db.Column(db.Boolean, default=False)

class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(60), nullable=False)
    from_date = db.Column(db.Date, nullable=False)
    to_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), default='Pending')

class ODRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(60), nullable=False)
    duty_date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(10), default='Pending')

# ---------- helpers ----------
def cur():
    return db.session.get(User, session['uid']) if 'uid' in session else None

def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = cur()
            if not u: return jsonify(error='Login required'), 401
            if roles and u.role not in roles: return jsonify(error='Not allowed'), 403
            return f(u, *a, **k)
        return w
    return deco

def fail(msg, code=400): return jsonify(error=msg), code

def ser(o):
    r = {}
    for c in o.__table__.columns:
        if c.name == 'password': continue
        v = getattr(o, c.name)
        r[c.name] = v.isoformat() if hasattr(v, 'isoformat') else v
    if hasattr(o, 'student_id'):
        s = db.session.get(User, o.student_id)
        if s: r.update(student_name=s.name, reg_no=s.login_id, department=s.department)
    return r

def haversine(a, b, c, d):
    R = 6371000; p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))

def summary(rows):
    n = len(rows); p = sum(r.status == 'Present' for r in rows); l = sum(r.status == 'Late' for r in rows)
    return dict(total=n, present=p, late=l, absent=n - p - l, pct=round((p + l) * 100 / n, 1) if n else 0)

def query_att(u, a):
    q = Attendance.query.join(User, User.id == Attendance.student_id)
    if u.role == 'student': q = q.filter(Attendance.student_id == u.id)
    if a.get('date'): q = q.filter(Attendance.day == date.fromisoformat(a['date']))
    if a.get('from'): q = q.filter(Attendance.day >= date.fromisoformat(a['from']))
    if a.get('to'): q = q.filter(Attendance.day <= date.fromisoformat(a['to']))
    if a.get('subject'): q = q.filter(Attendance.subject.ilike('%' + a['subject'] + '%'))
    if a.get('status'): q = q.filter(Attendance.status == a['status'])
    if a.get('q'): q = q.filter(db.or_(User.login_id.ilike('%' + a['q'] + '%'), User.name.ilike('%' + a['q'] + '%')))
    return q.order_by(Attendance.day.desc(), Attendance.id.desc()).all()

@app.after_request
def nocache(r):
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return r

@app.get('/')
def home(): return redirect('/pages/login.html')

# ---------- auth ----------
@app.post('/api/login')
def login():
    d = request.json or {}
    role = (d.get('role') or '').strip()
    if role not in ('student','faculty','principal'): return fail('Invalid role', 400)
    u = User.query.filter_by(login_id=(d.get('id') or '').strip(), role=role).first()
    if not u or not check_password_hash(u.password, d.get('password') or ''):
        return fail('Invalid ID or password', 401)
    session.clear(); session['uid'] = u.id
    return jsonify(user=ser(u))

@app.post('/api/logout')
def logout():
    session.clear(); return jsonify(ok=True)

@app.get('/api/me')
@need()
def me(u): return jsonify(user=ser(u))

# ---------- dashboard / students ----------
def counts(M, uid=None):
    base = M.query.filter_by(student_id=uid) if uid else M.query
    return {s: base.filter(M.status == s).count() for s in ('Pending', 'Approved', 'Rejected')}

@app.get('/api/dashboard')
@need()
def dashboard(u):
    stu = u.role == 'student'
    allrows = query_att(u, {})
    if stu:
        stats = summary(allrows); recent = allrows[:8]
    else:
        today = [r for r in allrows if r.day == local_today()]
        stats = summary(today); stats['pct'] = summary(allrows)['pct']
        stats['students'] = User.query.filter_by(role='student').count()
        recent = today[:8]
    uid = u.id if stu else None
    return jsonify(stats=stats, recent=[ser(r) for r in recent],
                   req=dict(leave=counts(LeaveRequest, uid), od=counts(ODRequest, uid)))

@app.get('/api/students')
@need('faculty', 'principal')
def students(u):
    out = []
    for s in User.query.filter_by(role='student').order_by(User.login_id).all():
        out.append(dict(
            id=s.id,
            reg_no=s.login_id,
            name=s.name,
            department=s.department,
            year=s.year,
            pct=summary(Attendance.query.filter_by(student_id=s.id).all())['pct']
        ))
    return jsonify(rows=out)


@app.post('/api/students')
@need('faculty', 'principal')
def add_student(u):
    d = request.json or {}

    reg_no = (d.get('reg_no') or '').strip()
    name = (d.get('name') or '').strip()
    department = (d.get('department') or '').strip()
    year = (d.get('year') or '').strip()
    password = d.get('password') or ''

    if not reg_no or not name or not department or not year or not password:
        return fail('Register number, name, department, year and password are required')

    if len(password) < 4:
        return fail('Password must contain at least 4 characters')

    if User.query.filter_by(login_id=reg_no).first():
        return fail('Register number already exists')

    s = User(
        login_id=reg_no,
        password=generate_password_hash(password),
        name=name,
        role='student',
        department=department,
        year=year
    )

    db.session.add(s)
    db.session.commit()

    return jsonify(ok=True, student=dict(
        id=s.id,
        reg_no=s.login_id,
        name=s.name,
        department=s.department,
        year=s.year,
        pct=0
    )), 201


@app.put('/api/students/<int:i>')
@need('faculty', 'principal')
def edit_student(u, i):
    s = db.session.get(User, i)

    if not s or s.role != 'student':
        return fail('Student not found', 404)

    d = request.json or {}

    name = (d.get('name') or '').strip()
    department = (d.get('department') or '').strip()
    year = (d.get('year') or '').strip()
    password = d.get('password')

    if not name or not department or not year:
        return fail('Name, department and year are required')

    s.name = name
    s.department = department
    s.year = year

    if password:
        if len(password) < 4:
            return fail('Password must contain at least 4 characters')
        s.password = generate_password_hash(password)

    db.session.commit()

    return jsonify(ok=True, student=dict(
        id=s.id,
        reg_no=s.login_id,
        name=s.name,
        department=s.department,
        year=s.year,
        pct=summary(Attendance.query.filter_by(student_id=s.id).all())['pct']
    ))


@app.delete('/api/students/<int:i>')
@need('faculty', 'principal')
def delete_student(u, i):
    s = db.session.get(User, i)

    if not s or s.role != 'student':
        return fail('Student not found', 404)

    # Remove related records first because the current schema uses
    # foreign keys without cascade delete.
    Attendance.query.filter_by(student_id=s.id).delete(synchronize_session=False)
    LeaveRequest.query.filter_by(student_id=s.id).delete(synchronize_session=False)
    ODRequest.query.filter_by(student_id=s.id).delete(synchronize_session=False)

    db.session.delete(s)
    db.session.commit()

    return jsonify(ok=True)


# ---------- principal / faculty management ----------
@app.get('/api/faculty')
@need('principal')
def list_faculty(u):
    rows = User.query.filter_by(role='faculty').order_by(User.login_id).all()
    return jsonify(rows=[dict(
        id=f.id,
        faculty_id=f.login_id,
        name=f.name,
        department=f.department
    ) for f in rows])

@app.post('/api/faculty')
@need('principal')
def add_faculty(u):
    d = request.json or {}
    faculty_id = (d.get('faculty_id') or '').strip()
    name = (d.get('name') or '').strip()
    department = (d.get('department') or '').strip()
    password = d.get('password') or ''

    if not faculty_id or not name or not department or not password:
        return fail('Faculty ID, name, department and password are required')
    if len(password) < 4:
        return fail('Password must contain at least 4 characters')
    if User.query.filter_by(login_id=faculty_id).first():
        return fail('Faculty ID already exists')

    f = User(
        login_id=faculty_id,
        password=generate_password_hash(password),
        name=name,
        role='faculty',
        department=department,
        year=''
    )
    db.session.add(f)
    db.session.commit()
    return jsonify(ok=True, faculty=dict(id=f.id, faculty_id=f.login_id, name=f.name, department=f.department)), 201

@app.put('/api/faculty/<int:i>')
@need('principal')
def edit_faculty(u, i):
    f = db.session.get(User, i)
    if not f or f.role != 'faculty':
        return fail('Faculty not found', 404)
    d = request.json or {}
    name = (d.get('name') or '').strip()
    department = (d.get('department') or '').strip()
    password = d.get('password')
    if not name or not department:
        return fail('Name and department are required')
    f.name = name
    f.department = department
    if password:
        if len(password) < 4:
            return fail('Password must contain at least 4 characters')
        f.password = generate_password_hash(password)
    db.session.commit()
    return jsonify(ok=True)

@app.delete('/api/faculty/<int:i>')
@need('principal')
def delete_faculty(u, i):
    f = db.session.get(User, i)
    if not f or f.role != 'faculty':
        return fail('Faculty not found', 404)
    if AttSession.query.filter_by(faculty_id=f.id).first():
        return fail('This faculty has attendance sessions and cannot be deleted.')
    db.session.delete(f)
    db.session.commit()
    return jsonify(ok=True)

# ---------- QR attendance ----------
@app.post('/api/sessions')
@need('faculty')
def create_session(u):
    d = request.json or {}
    subj = (d.get('subject') or '').strip()
    close_raw = (d.get('close_time') or '').strip()
    try: lat, lng = float(d['lat']), float(d['lng'])
    except Exception: return fail('Location is required to create a session')
    if not subj: return fail('Subject is required')
    try:
        close_at = datetime.strptime(close_raw, '%H:%M').time()
    except Exception:
        return fail('Valid session close time is required (HH:MM)')
    now = local_now()
    if close_at <= now.time().replace(second=0, microsecond=0):
        return fail('Session close time must be later than the current time')
    s = AttSession(faculty_id=u.id, subject=subj, token=secrets.token_urlsafe(24), lat=lat, lng=lng, close_at=close_at)
    db.session.add(s); db.session.flush()
    for st in User.query.filter_by(role='student').all():  # everyone starts Absent until they scan
        db.session.add(Attendance(student_id=st.id, session_id=s.id, subject=subj, day=s.day, status='Absent'))
    db.session.commit()
    return jsonify(session=ser(s))

@app.post('/api/attendance/scan')
@need('student')
def scan(u):
    d = request.json or {}
    s = AttSession.query.filter_by(token=d.get('token') or '').first()
    if not s: return fail('Invalid QR code')
    now = local_now(); t = now.time()
    if s.day != now.date(): return fail('This QR session has expired')
    if not DEV and s.close_at and t >= s.close_at: return fail(f'Attendance session is closed (closed at {s.close_at.strftime("%I:%M %p")})')
    try: lat, lng = float(d['lat']), float(d['lng'])
    except Exception: return fail('Location permission is required')
    dist = haversine(lat, lng, s.lat, s.lng)
    if dist > RADIUS: return fail(f'You are {round(dist)} m away. You must be within {RADIUS} m of the faculty.')
    rec = Attendance.query.filter_by(student_id=u.id, session_id=s.id).first()
    if not rec: rec = Attendance(student_id=u.id, session_id=s.id, subject=s.subject, day=s.day); db.session.add(rec)
    if rec.marked: return fail('Attendance already recorded for this session')
    start_at = s.created_at.time() if s.created_at else t
    start_minutes = start_at.hour * 60 + start_at.minute
    current_minutes = t.hour * 60 + t.minute
    rec.status = 'Late' if current_minutes >= start_minutes + LATE_AFTER_MINUTES else 'Present'; rec.at = t.replace(microsecond=0); rec.marked = True
    db.session.commit()
    return jsonify(message='Attendance Recorded', status=rec.status, subject=s.subject, distance=round(dist))

@app.get('/api/attendance')
@need()
def attendance(u):
    rows = query_att(u, request.args)
    return jsonify(rows=[ser(r) for r in rows], summary=summary(rows))

@app.put('/api/attendance/<int:i>')
@need('faculty')
def set_status(u, i):
    st = (request.json or {}).get('status')
    r = db.session.get(Attendance, i)
    if not r or st not in ('Present', 'Late', 'Absent'): return fail('Invalid request')
    r.status = st; r.marked = True
    if st != 'Absent' and not r.at: r.at = local_now().time().replace(microsecond=0)
    db.session.commit(); return jsonify(ok=True)

# ---------- leave / OD ----------
def req_routes(M, ep, required):
    def lst(u):
        q = M.query.order_by(M.id.desc())
        if u.role == 'student': q = q.filter_by(student_id=u.id)
        return jsonify(rows=[ser(r) for r in q.all()])
    def add(u):
        d = request.json or {}
        if any(not str(d.get(k, '')).strip() for k in required): return fail('Please fill all required fields')
        try:
            vals = {k: (date.fromisoformat(d[k]) if k.endswith('date') else d[k].strip()) for k in required}
        except ValueError: return fail('Invalid date')
        if 'to_date' in vals and vals['to_date'] < vals['from_date']: return fail('To Date cannot be before From Date')
        db.session.add(M(student_id=u.id, **vals)); db.session.commit(); return jsonify(ok=True)
    def decide(u, i):
        st = (request.json or {}).get('status'); r = db.session.get(M, i)
        if not r or st not in ('Approved', 'Rejected'): return fail('Invalid request')
        r.status = st; db.session.commit(); return jsonify(ok=True)
    app.add_url_rule(f'/api/{ep}', f'{ep}_l', need()(lst), methods=['GET'])
    app.add_url_rule(f'/api/{ep}', f'{ep}_a', need('student')(add), methods=['POST'])
    app.add_url_rule(f'/api/{ep}/<int:i>', f'{ep}_d', need('faculty')(decide), methods=['PUT'])

req_routes(LeaveRequest, 'leave', ['type', 'from_date', 'to_date', 'reason'])
req_routes(ODRequest, 'od', ['type', 'duty_date', 'location', 'reason'])

# ---------- seed ----------
def seed():
    """Create tables and ensure the initial Principal account exists.

    No demo student/faculty records are created. All later records are
    created through the Principal/Faculty screens and are persisted in the
    configured database.
    """
    db.create_all()
    # Add the close_at column when upgrading an existing AttendX database.
    try:
        from sqlalchemy import inspect, text
        if 'close_at' not in {c['name'] for c in inspect(db.engine).get_columns('att_session')}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE att_session ADD COLUMN close_at TIME'))
    except Exception:
        pass

    # Migrate the old "admin" role/name used by earlier builds.
    old_admins = User.query.filter_by(role='admin').all()
    for a in old_admins:
        a.role = 'principal'
        if a.login_id.lower() == 'admin':
            a.login_id = 'principal'
        a.password = generate_password_hash('principal123')
    db.session.commit()

    principal = User.query.filter_by(role='principal').first()
    if principal is None:
        principal = User(
            login_id='principal',
            password=generate_password_hash('principal123'),
            name='Principal',
            role='principal',
            department='',
            year=''
        )
        db.session.add(principal)
        db.session.commit()
    else:
        # Keep the initial account usable after a fresh/repaired install.
        principal.login_id = principal.login_id or 'principal'
        if principal.login_id == 'principal':
            principal.password = generate_password_hash('principal123')
        if not principal.name:
            principal.name = 'Principal'
        db.session.commit()

with app.app_context(): seed()

if __name__ == '__main__':
    print('AttendX time zone: Asia/Kolkata (IST)')
    print('AttendX database:', app.config['SQLALCHEMY_DATABASE_URI'])
    app.run(debug=True, port=5000)
