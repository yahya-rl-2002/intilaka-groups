#!/usr/bin/env python3
"""Intilaka Group website and reservation API (standard-library only)."""
from __future__ import annotations
import csv, hashlib, hmac, io, json, os, re, secrets, smtplib, sqlite3, threading, time
from datetime import date, datetime, timezone
from email.message import EmailMessage
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("INTILAKA_DB", str(DATA_DIR / "intilaka.db"))).resolve()
HOST = os.environ.get("INTILAKA_HOST", "127.0.0.1")
PORT = int(os.environ.get("INTILAKA_PORT", "4173"))
SESSIONS: dict[str, tuple[float, str]] = {}
SUBMISSION_LOG: dict[str, list[float]] = {}
ALLOWED_SERVICES = {"studies", "visa", "general"}
ALLOWED_TIMES = {"09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00"}
ALLOWED_STATUSES = {"pending", "confirmed", "completed", "cancelled"}
BUSINESS_TZ = ZoneInfo(os.environ.get("INTILAKA_TZ", "Africa/Casablanca"))
CLOSED_WEEKDAYS = {6}  # Monday=0 ... Sunday=6
AUTH_FAILURES: dict[str, list[float]] = {}
AUTH_MAX_FAILURES = 5
AUTH_WINDOW_SECONDS = 900
SETUP_TOKEN = os.environ.get("INTILAKA_SETUP_TOKEN") or secrets.token_urlsafe(16)
# Only these files are ever served. Everything else in the folder (database, source, backups) stays private.
PUBLIC_FILES = frozenset({
    "index.html", "site.css", "site.js",
    "admin.html", "admin.css", "admin.js", "admin-calendar.css", "admin-calendar.js",
    "assets/intilaka-advisor-hero.jpg", "assets/intilaka-advisor-hero.png", "assets/cas-residence-masque.jpg",
    "Instagram/imgi_2_722953413_17978082870013708_4713938570986959581_n.jpg",
    "Instagram/imgi_12_774008361_1536788880991438_3124231926748838089_n.jpg",
    "Instagram/imgi_13_741000898_17981658114013708_8256144421396316375_n.jpg",
    "Instagram/imgi_16_755464572_17983926039013708_2483299330115498558_n.jpg",
    "Instagram/imgi_17_744784266_17982399588013708_8386952833328561752_n.jpg",
    "Instagram/imgi_18_746557481_17982272163013708_1723450230050494446_n.jpg",
    "Instagram/imgi_19_743940461_17982139191013708_4190382884018373688_n.jpg",
})

def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS admin (
          id INTEGER PRIMARY KEY CHECK(id=1), salt TEXT NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reservations (
          id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
          service TEXT NOT NULL, appointment_date TEXT NOT NULL,
          appointment_time TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
          language TEXT NOT NULL DEFAULT 'ar', status TEXT NOT NULL DEFAULT 'pending',
          notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS active_reservation_slot
        ON reservations(appointment_date, appointment_time)
        WHERE status != 'cancelled';
        """)

def password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000).hex()

def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")

def setup_required():
    with db() as connection:
        return connection.execute("SELECT 1 FROM admin WHERE id=1").fetchone() is None

def send_notification(message):
    host, port = os.environ["INTILAKA_SMTP_HOST"], int(os.environ.get("INTILAKA_SMTP_PORT", "587"))
    user, password = os.environ.get("INTILAKA_SMTP_USER"), os.environ.get("INTILAKA_SMTP_PASSWORD")
    try:
        with (smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)) as smtp:
            if port != 465:
                smtp.ehlo()
                if smtp.has_extn("starttls"): smtp.starttls(); smtp.ehlo()
                elif user: raise smtplib.SMTPException("STARTTLS unavailable, refusing to send the password in clear text")
            if user: smtp.login(user, password or "")
            smtp.send_message(message)
        print(f"[notification] envoyée pour {message['X-Intilaka-Reference']}")
    except (OSError, smtplib.SMTPException) as error:
        print(f"[notification] ÉCHEC pour {message['X-Intilaka-Reference']} : {type(error).__name__}: {error}")

def notify_new_reservation(values, reference):
    recipient = os.environ.get("INTILAKA_NOTIFY_TO")
    if not (recipient and os.environ.get("INTILAKA_SMTP_HOST")):
        print(f"[notification] non configurée, nouvelle demande {reference} visible dans /admin")
        return
    message = EmailMessage()
    message["Subject"] = f"Nouvelle demande {reference} — {values['date']} à {values['time']}"
    message["From"] = os.environ.get("INTILAKA_SMTP_USER") or recipient
    message["To"] = recipient
    message["X-Intilaka-Reference"] = reference
    message.set_content(
        f"Référence : {reference}\nNom : {values['name']}\nWhatsApp : {values['phone']}\n"
        f"E-mail : {values['email'] or '—'}\nRendez-vous : {values['date']} à {values['time']}\n\n{values['message']}\n"
    )
    threading.Thread(target=send_notification, args=(message,), daemon=True).start()

class Handler(SimpleHTTPRequestHandler):
    server_version = "Intilaka/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status, payload, headers=None):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20_000: raise ValueError("Payload too large")
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def session(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        token = jar.get("intilaka_session")
        if not token: return None
        stored = SESSIONS.get(token.value)
        if not stored or stored[0] < time.time():
            SESSIONS.pop(token.value, None); return None
        return token.value, stored[1]

    def require_admin(self):
        session = self.session()
        if not session: self.send_json(401, {"error": "authentication_required"}); return None
        if self.command in {"POST", "PATCH", "DELETE"} and self.headers.get("X-CSRF-Token") != session[1]:
            self.send_json(403, {"error": "invalid_csrf"}); return None
        return session

    def send_head(self):
        # Checked on the path the filesystem will really open, so URL spellings like /./data or /%64ata cannot slip through.
        target = Path(self.translate_path(self.path)).resolve()
        if target != ROOT and (not target.is_relative_to(ROOT) or target.relative_to(ROOT).as_posix() not in PUBLIC_FILES):
            self.send_error(404)
            return None
        return super().send_head()

    def recent_auth_failures(self):
        now = time.time()
        recent = [stamp for stamp in AUTH_FAILURES.get(self.client_address[0], []) if now - stamp < AUTH_WINDOW_SECONDS]
        AUTH_FAILURES[self.client_address[0]] = recent
        return recent

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/admin": self.path = "/admin.html"; return super().do_GET()
        if parsed.path == "/api/availability": return self.availability(parsed)
        if parsed.path == "/api/admin/state": return self.admin_state()
        if parsed.path == "/api/admin/reservations": return self.list_reservations(parsed)
        if parsed.path == "/api/admin/export.csv": return self.export_csv()
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/reservations": return self.create_reservation()
        if path == "/api/admin/setup": return self.admin_setup()
        if path == "/api/admin/login": return self.admin_login()
        if path == "/api/admin/logout": return self.admin_logout()
        self.send_json(404, {"error": "not_found"})

    def do_PATCH(self):
        match = re.fullmatch(r"/api/admin/reservations/(\d+)", urlparse(self.path).path)
        if match: return self.update_reservation(int(match.group(1)))
        self.send_json(404, {"error": "not_found"})

    def availability(self, parsed):
        selected = parse_qs(parsed.query).get("date", [""])[0]
        try: selected_date = date.fromisoformat(selected)
        except ValueError: return self.send_json(400, {"error": "invalid_date"})
        now = datetime.now(BUSINESS_TZ)
        past = [slot for slot in ALLOWED_TIMES if selected_date == now.date() and slot <= now.strftime("%H:%M")]
        with db() as connection:
            rows = connection.execute("SELECT appointment_time FROM reservations WHERE appointment_date=? AND status!='cancelled'", (selected,)).fetchall()
        self.send_json(200, {"date": selected, "booked": [row[0] for row in rows], "past": past, "closed": selected_date.weekday() in CLOSED_WEEKDAYS})

    def create_reservation(self):
        client_ip = self.client_address[0]
        now_seconds = time.time()
        recent = [stamp for stamp in SUBMISSION_LOG.get(client_ip, []) if now_seconds - stamp < 600]
        if len(recent) >= 8: return self.send_json(429, {"error": "too_many_requests"})
        recent.append(now_seconds); SUBMISSION_LOG[client_ip] = recent
        data = self.read_json()
        if data is None: return self.send_json(400, {"error": "invalid_json"})
        values = {key: str(data.get(key, "")).strip() for key in ("name","phone","email","service","date","time","message","language")}
        if len(values["name"]) < 2 or len(values["name"]) > 100: return self.send_json(400, {"error": "invalid_name"})
        if not re.fullmatch(r"[+0-9 ()-]{7,30}", values["phone"]): return self.send_json(400, {"error": "invalid_phone"})
        if values["email"] and (len(values["email"]) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"])): return self.send_json(400, {"error": "invalid_email"})
        if values["service"] not in ALLOWED_SERVICES: return self.send_json(400, {"error": "invalid_service"})
        if values["time"] not in ALLOWED_TIMES: return self.send_json(400, {"error": "invalid_time"})
        try: selected_date = date.fromisoformat(values["date"])
        except ValueError: return self.send_json(400, {"error": "invalid_date"})
        now_local = datetime.now(BUSINESS_TZ)
        if selected_date < now_local.date(): return self.send_json(400, {"error": "past_date"})
        if selected_date == now_local.date() and values["time"] <= now_local.strftime("%H:%M"): return self.send_json(400, {"error": "past_time"})
        if selected_date.weekday() in CLOSED_WEEKDAYS: return self.send_json(400, {"error": "closed_day"})
        if len(values["message"]) > 1000: return self.send_json(400, {"error": "message_too_long"})
        now = datetime.now(timezone.utc).isoformat(); reference = "INT-" + secrets.token_hex(3).upper()
        try:
            with db() as connection:
                connection.execute("INSERT INTO reservations(reference,name,phone,email,service,appointment_date,appointment_time,message,language,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (reference,values["name"],values["phone"],values["email"],values["service"],values["date"],values["time"],values["message"],values["language"] or "ar",now,now))
        except sqlite3.IntegrityError:
            return self.send_json(409, {"error": "slot_unavailable"})
        notify_new_reservation(values, reference)
        self.send_json(201, {"ok": True, "reference": reference})

    def admin_state(self):
        session = self.session()
        self.send_json(200, {"setupRequired": setup_required(), "authenticated": bool(session), "csrf": session[1] if session else None})

    def admin_setup(self):
        if len(self.recent_auth_failures()) >= AUTH_MAX_FAILURES: return self.send_json(429, {"error": "too_many_attempts"})
        data = self.read_json() or {}; password = str(data.get("password", ""))
        if not hmac.compare_digest(str(data.get("token", "")).encode(), SETUP_TOKEN.encode()):
            self.recent_auth_failures().append(time.time())
            return self.send_json(403, {"error": "invalid_setup_token"})
        if len(password) < 10: return self.send_json(400, {"error": "password_too_short"})
        salt = secrets.token_bytes(16); now = datetime.now(timezone.utc).isoformat()
        try:
            with db() as connection: connection.execute("INSERT INTO admin(id,salt,password_hash,created_at) VALUES(1,?,?,?)", (salt.hex(),password_hash(password,salt),now))
        except sqlite3.IntegrityError: return self.send_json(409, {"error": "already_configured"})
        return self.start_session()

    def admin_login(self):
        if len(self.recent_auth_failures()) >= AUTH_MAX_FAILURES: return self.send_json(429, {"error": "too_many_attempts"})
        data = self.read_json() or {}; password = str(data.get("password", ""))
        with db() as connection: row = connection.execute("SELECT salt,password_hash FROM admin WHERE id=1").fetchone()
        if not row or not hmac.compare_digest(password_hash(password,bytes.fromhex(row["salt"])),row["password_hash"]):
            self.recent_auth_failures().append(time.time())
            time.sleep(.35); return self.send_json(401, {"error": "invalid_credentials"})
        AUTH_FAILURES.pop(self.client_address[0], None)
        self.start_session()

    def start_session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24); SESSIONS[token] = (time.time()+28_800, csrf)
        cookie = f"intilaka_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"
        self.send_json(200, {"ok": True, "csrf": csrf}, {"Set-Cookie": cookie})

    def admin_logout(self):
        session = self.require_admin()
        if not session: return
        SESSIONS.pop(session[0], None)
        self.send_json(200, {"ok": True}, {"Set-Cookie": "intilaka_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})

    def list_reservations(self, parsed):
        if not self.require_admin(): return
        query = parse_qs(parsed.query); status = query.get("status", [""])[0]; search = query.get("q", [""])[0][:100]
        clauses, params = [], []
        if status in ALLOWED_STATUSES: clauses.append("status=?"); params.append(status)
        if search: clauses.append("(name LIKE ? OR phone LIKE ? OR email LIKE ? OR reference LIKE ?)"); params += [f"%{search}%"]*4
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with db() as connection:
            rows = connection.execute("SELECT * FROM reservations"+where+" ORDER BY appointment_date ASC, appointment_time ASC", params).fetchall()
            counts = {row["status"]:row["count"] for row in connection.execute("SELECT status,COUNT(*) count FROM reservations GROUP BY status")}
        self.send_json(200, {"reservations":[dict(row) for row in rows], "counts":counts})

    def update_reservation(self, reservation_id):
        if not self.require_admin(): return
        data = self.read_json() or {}; status = data.get("status"); notes = str(data.get("notes", ""))[:2000]
        if status not in ALLOWED_STATUSES: return self.send_json(400, {"error": "invalid_status"})
        try:
            with db() as connection:
                result = connection.execute("UPDATE reservations SET status=?,notes=?,updated_at=? WHERE id=?", (status,notes,datetime.now(timezone.utc).isoformat(),reservation_id))
                if result.rowcount == 0: return self.send_json(404, {"error": "not_found"})
        except sqlite3.IntegrityError: return self.send_json(409, {"error":"slot_unavailable"})
        self.send_json(200, {"ok":True})

    def export_csv(self):
        if not self.require_admin(): return
        with db() as connection: rows = connection.execute("SELECT reference,name,phone,email,service,appointment_date,appointment_time,status,message,notes,created_at FROM reservations ORDER BY appointment_date,appointment_time").fetchall()
        stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(rows[0].keys() if rows else ["reference","name","phone","email","service","appointment_date","appointment_time","status","message","notes","created_at"]); writer.writerows([tuple(row) for row in rows]); body = stream.getvalue().encode("utf-8-sig")
        self.send_response(200); self.send_header("Content-Type","text/csv; charset=utf-8"); self.send_header("Content-Disposition",'attachment; filename="reservations-intilaka.csv"'); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    init_db()
    print(f"Intilaka: http://{HOST}:{PORT}")
    print(f"Administration: http://{HOST}:{PORT}/admin")
    if setup_required(): print(f"Code de première configuration admin : {SETUP_TOKEN}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
