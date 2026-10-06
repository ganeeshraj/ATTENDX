# ATTENDX – PORTABLE QR ATTENDANCE

## Easy Run
1. Extract the ZIP.
2. Double-click `RUN_ATTENDX.bat`.
3. Wait for the browser to open.
4. Select **Principal** and sign in with the initial Principal account below.

### Initial Principal Login
- Username: `principal`
- Password: `principal123`

This is the only account created automatically. No demo students or demo faculty are included.

### Backend saving
All Principal, Faculty, Student, attendance, Leave and OD records are saved in the database configured by the application.

- By default, the app uses SQLite and stores the database as `backend/attendx.db`.
- For MySQL, copy `backend/.env.example` to `backend/.env` and configure the database values before starting the app.
- The Principal can add, edit and delete faculty records from **Faculty Management**.
- Faculty can add, edit and delete students from **Students**.
- Passwords are stored as secure password hashes, not plain text.

### Important
Do not open the HTML file directly. Always start the backend with `RUN_ATTENDX.bat`, then use the browser page opened by the application.

## Roles
**Principal**
- Faculty Management
- Attendance reports
- Leave / OD request viewing

**Faculty**
- Student Management
- Create QR attendance
- Attendance management
- Leave / OD processing

**Student**
- Scan QR
- View attendance
- Submit Leave / OD requests
- View reports


### QR Session Timing
- Session start time is automatic when the faculty creates the session.
- The faculty is asked only for the Session Close Time (`HH:MM`).
- The QR is accepted only before the configured close time and is automatically hidden on the faculty screen at close.
- Attendance is marked `Late` when scanned 15 or more minutes after the automatic session start.
