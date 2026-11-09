#!/usr/bin/env python3
"""Intilaka Group website and reservation API (standard-library only)."""
from __future__ import annotations
import csv, getpass, hashlib, hmac, io, json, os, re, secrets, sqlite3, sys, time
from datetime import date, datetime, timezone
from http import cookies
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import pointage

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("INTILAKA_DB", str(DATA_DIR / "intilaka.db"))).resolve()
HOST = os.environ.get("INTILAKA_HOST", "127.0.0.1")
PORT = int(os.environ.get("INTILAKA_PORT", "4173"))
# Production flags: behind a HTTPS reverse proxy (Caddy), set these to "1" / "0".
TRUST_PROXY = os.environ.get("INTILAKA_TRUST_PROXY") == "1"
SECURE_COOKIES = os.environ.get("INTILAKA_SECURE_COOKIES") == "1"
WEB_SETUP = os.environ.get("INTILAKA_WEB_SETUP", "1") == "1"
SESSIONS: dict[str, tuple[float, str]] = {}
SUBMISSION_LOG: dict[str, list[float]] = {}
LOGIN_FAILURES: dict[str, list[float]] = {}
ALLOWED_LANGUAGES = {"ar", "fr", "en"}
# Only these file types are ever served; everything else (source, database, dotfiles, folders) is a 404.
STATIC_EXTENSIONS = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".gif", ".woff", ".woff2"}
BLOCKED_DIRS = {"data", "deploy", "__pycache__"}
ALLOWED_SERVICES = {"studies", "visa", "general"}
ALLOWED_TIMES = {"09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00"}
ALLOWED_STATUSES = {"pending", "confirmed", "completed", "cancelled"}

def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

pointage.connect = db

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        pointage.init_db(connection)
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

def recent_hits(log, key, window):
    now = time.time()
    hits = [stamp for stamp in log.get(key, []) if now - stamp < window]
    if hits: log[key] = hits
    else: log.pop(key, None)
    return hits

def prune(log, window):
    for key in list(log): recent_hits(log, key, window)

def csv_safe(value):
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")

class Handler(SimpleHTTPRequestHandler):
    server_version = "Intilaka"
    sys_version = ""
    timeout = 20

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def end_headers(self):
        # Pages, CSS and JS are revalidated on every visit so updates show up immediately (cheap 304 when unchanged).
        if self.command in {"GET", "HEAD"} and not getattr(self, "_json_response", False):
            if Path(urlparse(self.path).path).suffix.lower() in {"", ".html", ".css", ".js"}: self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, status, payload, headers=None):
        self._json_response = True
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items(): self.send_header(key, value)
        self.end_headers(); self.wfile.write(body)

    def read_json(self):
        if not self.headers.get("Content-Type", "").startswith("application/json"): return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 20_000: raise ValueError("Invalid payload size")
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def send_head(self):
        # Shared by GET and HEAD: decode the path before checking it so "%73erver.py" cannot slip through.
        path = unquote(urlparse(self.path).path)
        parts = [part for part in path.split("/") if part]
        if path in {"/", "/index.html", "/admin.html"}:
            pass
        elif (not parts or ".." in parts or any(part.startswith(".") for part in parts) or parts[0] in BLOCKED_DIRS
              or Path(path).suffix.lower() not in STATIC_EXTENSIONS or not (ROOT / Path(*parts)).is_file()):
            self.send_error(404); return None
        return super().send_head()

    def client_ip(self):
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
            if forwarded: return forwarded
        return self.client_address[0]

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

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/admin": self.path = "/admin.html"; return super().do_GET()
        if parsed.path == "/admin/pointage": self.path = "/admin-pointage.html"; return super().do_GET()
        if parsed.path == "/pointage": self.path = "/pointage.html"; return super().do_GET()
        if pointage.handle(self, "GET", parsed.path, parse_qs(parsed.query)): return
        if parsed.path == "/api/availability": return self.availability(parsed)
        if parsed.path == "/api/admin/state": return self.admin_state()
        if parsed.path == "/api/admin/reservations": return self.list_reservations(parsed)
        if parsed.path == "/api/admin/export.csv": return self.export_csv()
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if pointage.handle(self, "POST", path, {}): return
        if path == "/api/reservations": return self.create_reservation()
        if path == "/api/admin/setup": return self.admin_setup()
        if path == "/api/admin/login": return self.admin_login()
        if path == "/api/admin/logout": return self.admin_logout()
        self.send_json(404, {"error": "not_found"})

    def do_PATCH(self):
        path = urlparse(self.path).path
        if pointage.handle(self, "PATCH", path, {}): return
        match = re.fullmatch(r"/api/admin/reservations/(\d+)", path)
        if match: return self.update_reservation(int(match.group(1)))
        self.send_json(404, {"error": "not_found"})

    def do_DELETE(self):
        if pointage.handle(self, "DELETE", urlparse(self.path).path, {}): return
        self.send_json(404, {"error": "not_found"})

    def availability(self, parsed):
        selected = parse_qs(parsed.query).get("date", [""])[0]
        try: date.fromisoformat(selected)
        except ValueError: return self.send_json(400, {"error": "invalid_date"})
        with db() as connection:
            rows = connection.execute("SELECT appointment_time FROM reservations WHERE appointment_date=? AND status!='cancelled'", (selected,)).fetchall()
        self.send_json(200, {"date": selected, "booked": [row[0] for row in rows]})

    def create_reservation(self):
        client_ip = self.client_ip()
        if len(SUBMISSION_LOG) > 5000: prune(SUBMISSION_LOG, 600)
        recent = recent_hits(SUBMISSION_LOG, client_ip, 600)
        if len(recent) >= 8: return self.send_json(429, {"error": "too_many_requests"})
        SUBMISSION_LOG[client_ip] = recent + [time.time()]
        data = self.read_json()
        if data is None: return self.send_json(400, {"error": "invalid_json"})
        # Honeypot: the "website" field is invisible to people, so only bots fill it. Pretend success.
        if str(data.get("website", "")).strip(): return self.send_json(201, {"ok": True, "reference": "INT-" + secrets.token_hex(3).upper()})
        values = {key: str(data.get(key, "")).strip() for key in ("name","phone","email","service","date","time","message","language")}
        if len(values["name"]) < 2 or len(values["name"]) > 100: return self.send_json(400, {"error": "invalid_name"})
        if not re.fullmatch(r"[+0-9 ()-]{7,30}", values["phone"]): return self.send_json(400, {"error": "invalid_phone"})
        if values["email"] and (len(values["email"]) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"])): return self.send_json(400, {"error": "invalid_email"})
        if values["service"] not in ALLOWED_SERVICES: return self.send_json(400, {"error": "invalid_service"})
        if values["time"] not in ALLOWED_TIMES: return self.send_json(400, {"error": "invalid_time"})
        try: selected_date = date.fromisoformat(values["date"])
        except ValueError: return self.send_json(400, {"error": "invalid_date"})
        if selected_date < date.today(): return self.send_json(400, {"error": "past_date"})
        if len(values["message"]) > 1000: return self.send_json(400, {"error": "message_too_long"})
        if values["language"] not in ALLOWED_LANGUAGES: values["language"] = "ar"
        now = datetime.now(timezone.utc).isoformat(); reference = "INT-" + secrets.token_hex(3).upper()
        try:
            with db() as connection:
                connection.execute("INSERT INTO reservations(reference,name,phone,email,service,appointment_date,appointment_time,message,language,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (reference,values["name"],values["phone"],values["email"],values["service"],values["date"],values["time"],values["message"],values["language"] or "ar",now,now))
        except sqlite3.IntegrityError:
            return self.send_json(409, {"error": "slot_unavailable"})
        self.send_json(201, {"ok": True, "reference": reference})

    def admin_state(self):
        with db() as connection: setup = connection.execute("SELECT 1 FROM admin WHERE id=1").fetchone() is None
        session = self.session()
        self.send_json(200, {"setupRequired": setup, "authenticated": bool(session), "csrf": session[1] if session else None})

    def admin_setup(self):
        if not WEB_SETUP: return self.send_json(403, {"error": "web_setup_disabled"})
        data = self.read_json() or {}; password = str(data.get("password", ""))
        if len(password) < 10: return self.send_json(400, {"error": "password_too_short"})
        salt = secrets.token_bytes(16); now = datetime.now(timezone.utc).isoformat()
        try:
            with db() as connection: connection.execute("INSERT INTO admin(id,salt,password_hash,created_at) VALUES(1,?,?,?)", (salt.hex(),password_hash(password,salt),now))
        except sqlite3.IntegrityError: return self.send_json(409, {"error": "already_configured"})
        return self.start_session()

    def admin_login(self):
        client_ip = self.client_ip()
        if len(LOGIN_FAILURES) > 5000: prune(LOGIN_FAILURES, 900)
        failures = recent_hits(LOGIN_FAILURES, client_ip, 900)
        if len(failures) >= 5: return self.send_json(429, {"error": "too_many_attempts"})
        data = self.read_json() or {}; password = str(data.get("password", ""))[:200]
        with db() as connection: row = connection.execute("SELECT salt,password_hash FROM admin WHERE id=1").fetchone()
        if not row or not hmac.compare_digest(password_hash(password,bytes.fromhex(row["salt"])),row["password_hash"]):
            LOGIN_FAILURES[client_ip] = failures + [time.time()]
            time.sleep(.35); return self.send_json(401, {"error": "invalid_credentials"})
        LOGIN_FAILURES.pop(client_ip, None)
        self.start_session()

    def start_session(self):
        for key, (expires, _) in list(SESSIONS.items()):
            if expires < time.time(): SESSIONS.pop(key, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24); SESSIONS[token] = (time.time()+28_800, csrf)
        cookie = f"intilaka_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800" + ("; Secure" if SECURE_COOKIES else "")
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
        stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(rows[0].keys() if rows else ["reference","name","phone","email","service","appointment_date","appointment_time","status","message","notes","created_at"]); writer.writerows([tuple(csv_safe(value) for value in row) for row in rows]); body = stream.getvalue().encode("utf-8-sig")
        self.send_response(200); self.send_header("Content-Type","text/csv; charset=utf-8"); self.send_header("Content-Disposition",'attachment; filename="reservations-intilaka.csv"'); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)

def set_password_cli():
    """Create or replace the admin password from the terminal (used on the server over SSH)."""
    password = getpass.getpass("Nouveau mot de passe administrateur (10 caractères minimum) : ")
    if len(password) < 10: sys.exit("Mot de passe trop court.")
    if getpass.getpass("Confirmez le mot de passe : ") != password: sys.exit("Les mots de passe ne correspondent pas.")
    salt = secrets.token_bytes(16); now = datetime.now(timezone.utc).isoformat()
    with db() as connection:
        connection.execute("INSERT OR REPLACE INTO admin(id,salt,password_hash,created_at) VALUES(1,?,?,?)", (salt.hex(),password_hash(password,salt),now))
    print("Mot de passe administrateur enregistré.")

if __name__ == "__main__":
    init_db()
    if "--set-password" in sys.argv: set_password_cli(); sys.exit()
    print(f"Intilaka: http://{HOST}:{PORT}")
    print(f"Administration: http://{HOST}:{PORT}/admin")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
