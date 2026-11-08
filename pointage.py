"""Staff time clock (pointage): employees punch from the office network with a PIN; the admin sees days, months and exports."""
from __future__ import annotations
import calendar, csv, hashlib, hmac, io, ipaddress, re, secrets, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

connect = None  # set by server.py to its db() factory

KIND_LABELS = {"in": "Arrivée", "break_start": "Début pause", "break_end": "Fin pause", "out": "Départ"}
ALLOWED_NEXT = {"out": ("in",), "in": ("break_start", "out"), "break": ("break_end", "out")}
STATUS_LABELS = {"present": "Au bureau", "break": "En pause", "left": "Parti", "done": "Journée complète", "missing_out": "Départ non pointé", "absent": "Absent", "waiting": "Pas encore arrivé", "off": "Repos"}
DEFAULTS = {"office_networks": "", "work_start": "09:00", "work_end": "18:00", "workdays": "0,1,2,3,4", "late_tolerance": "10", "timezone": "Africa/Casablanca"}
TIMEZONES = {"Africa/Casablanca": "Maroc (Tétouan)", "Europe/Madrid": "Espagne (Malaga)"}
PIN_FAILURES: dict[str, list[float]] = {}
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, salt TEXT NOT NULL,
  pin_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS punches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL REFERENCES employees(id),
  kind TEXT NOT NULL, at TEXT NOT NULL, ip TEXT NOT NULL DEFAULT '',
  manual INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS punches_at ON punches(at);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

def init_db(connection):
    connection.executescript(SCHEMA)

def pin_hash(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 120_000).hex()

def load_settings(connection):
    cfg = dict(DEFAULTS)
    cfg.update({row[0]: row[1] for row in connection.execute("SELECT key,value FROM settings")})
    return cfg

def networks(cfg):
    return [item for item in cfg["office_networks"].split(",") if item]

def workdays(cfg):
    return {int(item) for item in cfg["workdays"].split(",") if item}

def office_allowed(ip, cfg):
    # No network configured yet = no restriction (the admin page warns about it).
    if not networks(cfg): return True
    try:
        address = ipaddress.ip_address(ip)
        if address.version == 6 and address.ipv4_mapped: address = address.ipv4_mapped
        return any(address in ipaddress.ip_network(item, strict=False) for item in networks(cfg))
    except ValueError:
        return False

def iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")

def day_bounds(day, tz):
    start = datetime.combine(day, datetime.min.time(), tz)
    return iso(start), iso(start + timedelta(days=1))

def local_time(stamp, tz):
    return datetime.fromisoformat(stamp).astimezone(tz).strftime("%H:%M")

def created_day(employee, tz):
    return datetime.fromisoformat(employee["created_at"]).astimezone(tz).date()

def minutes_of(value):
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)

def punches_between(connection, start, end, employee_id=None):
    sql, params = "SELECT id,employee_id,kind,at,manual,note FROM punches WHERE at>=? AND at<?", [start, end]
    if employee_id is not None: sql += " AND employee_id=?"; params.append(employee_id)
    return connection.execute(sql + " ORDER BY at,id", params).fetchall()

def state_of(punches):
    if not punches: return "out"
    return {"in": "in", "break_end": "in", "break_start": "break", "out": "out"}[punches[-1]["kind"]]

def summarize(punches, day, tz, cfg, now, created):
    """Worked/break minutes, arrival, departure, lateness and status of one employee for one local day."""
    worked = breaks = 0.0; start = pause = first_in = last_out = None
    for kind, at in ((row["kind"], datetime.fromisoformat(row["at"]).astimezone(tz)) for row in punches):
        if kind == "in" and start is None and pause is None:
            start = at; first_in = first_in or at
        elif kind == "break_start" and start is not None:
            worked += (at - start).total_seconds(); start, pause = None, at
        elif kind == "break_end" and pause is not None:
            breaks += (at - pause).total_seconds(); start, pause = at, None
        elif kind == "out":
            if start is not None: worked += (at - start).total_seconds()
            if pause is not None: breaks += (at - pause).total_seconds()
            start = pause = None; last_out = at
    is_today, still_open = day == now.date(), start is not None or pause is not None
    if still_open and is_today:
        if start is not None: worked += (now - start).total_seconds()
        if pause is not None: breaks += (now - pause).total_seconds()
    scheduled = day.weekday() in workdays(cfg)
    expected, tolerance = minutes_of(cfg["work_start"]), int(cfg["late_tolerance"])
    late = 0
    if scheduled and first_in:
        arrived = first_in.hour * 60 + first_in.minute
        if arrived > expected + tolerance: late = arrived - expected
    if punches:
        status = {"in": "present", "break": "break", "out": "left"}[state_of(punches)] if is_today else ("missing_out" if still_open else "done")
    elif not scheduled or day < created:
        status = "off"
    elif day < now.date() or (is_today and now.hour * 60 + now.minute > expected + tolerance):
        status = "absent"
    else:
        status = "waiting"
    return {"worked": round(worked / 60), "breaks": round(breaks / 60), "first_in": first_in.strftime("%H:%M") if first_in else "",
            "last_out": last_out.strftime("%H:%M") if last_out else "", "late": late, "missing_out": still_open and not is_today, "status": status}

def recent_failures(key):
    now = time.time()
    if len(PIN_FAILURES) > 5000:
        for stale in [k for k, v in PIN_FAILURES.items() if not v or now - v[-1] > 900]: PIN_FAILURES.pop(stale, None)
    hits = [stamp for stamp in PIN_FAILURES.get(key, []) if now - stamp < 900]
    PIN_FAILURES[key] = hits
    return hits

def csv_safe(value):
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

def hours_text(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"

# ---------- routing ----------

def handle(h, method, path, query):
    """Serve a time-clock API request; return False when the path is not ours."""
    routes = {
        ("GET", "/api/pointage/employees"): public_employees,
        ("POST", "/api/pointage/status"): employee_status,
        ("POST", "/api/pointage/punch"): employee_punch,
        ("GET", "/api/admin/pointage/overview"): admin_overview,
        ("GET", "/api/admin/pointage/month"): admin_month,
        ("GET", "/api/admin/pointage/export.csv"): admin_export,
        ("POST", "/api/admin/pointage/settings"): admin_settings,
        ("POST", "/api/admin/pointage/employees"): admin_create_employee,
        ("POST", "/api/admin/pointage/punches"): admin_add_punch,
    }
    if (method, path) in routes:
        if path.startswith("/api/admin/") and not h.require_admin(): return True
        routes[(method, path)](h, query); return True
    match = re.fullmatch(r"/api/admin/pointage/(employees|punches)/(\d+)", path)
    if match and (method, match.group(1)) in {("PATCH", "employees"), ("DELETE", "punches")}:
        if not h.require_admin(): return True
        (admin_update_employee if match.group(1) == "employees" else admin_delete_punch)(h, int(match.group(2))); return True
    return False

# ---------- employee side ----------

def public_employees(h, query):
    with connect() as connection:
        if not office_allowed(h.client_ip(), load_settings(connection)): return h.send_json(403, {"error": "office_network_required"})
        rows = connection.execute("SELECT id,name FROM employees WHERE active=1 ORDER BY name COLLATE NOCASE").fetchall()
        tz = load_settings(connection)["timezone"]
    h.send_json(200, {"employees": [dict(row) for row in rows], "timezone": tz})

def authenticate(h, connection, data):
    cfg, ip = load_settings(connection), h.client_ip()
    if not office_allowed(ip, cfg): h.send_json(403, {"error": "office_network_required"}); return None, cfg
    try: employee_id = int(data.get("employee_id"))
    except (TypeError, ValueError): h.send_json(400, {"error": "invalid_employee"}); return None, cfg
    keys = ("ip:" + ip, f"employee:{employee_id}")
    if len(recent_failures(keys[0])) >= 10 or len(recent_failures(keys[1])) >= 5:
        h.send_json(429, {"error": "too_many_attempts"}); return None, cfg
    employee = connection.execute("SELECT * FROM employees WHERE id=? AND active=1", (employee_id,)).fetchone()
    pin = str(data.get("pin", ""))[:20]
    if not employee or not hmac.compare_digest(pin_hash(pin, bytes.fromhex(employee["salt"])), employee["pin_hash"]):
        for key in keys: PIN_FAILURES.setdefault(key, []).append(time.time())
        time.sleep(.3); h.send_json(401, {"error": "invalid_pin"}); return None, cfg
    PIN_FAILURES.pop(keys[1], None)
    return employee, cfg

def employee_today(connection, employee, cfg):
    tz = ZoneInfo(cfg["timezone"]); now = datetime.now(timezone.utc).astimezone(tz)
    rows = punches_between(connection, *day_bounds(now.date(), tz), employee["id"])
    state = state_of(rows)
    return {"name": employee["name"], "state": state, "next": list(ALLOWED_NEXT[state]),
            "punches": [{"kind": row["kind"], "time": local_time(row["at"], tz)} for row in rows],
            "summary": summarize(rows, now.date(), tz, cfg, now, created_day(employee, tz))}

def employee_status(h, query):
    data = h.read_json()
    if data is None: return h.send_json(400, {"error": "invalid_json"})
    with connect() as connection:
        employee, cfg = authenticate(h, connection, data)
        if employee: h.send_json(200, employee_today(connection, employee, cfg))

def employee_punch(h, query):
    data = h.read_json()
    if data is None: return h.send_json(400, {"error": "invalid_json"})
    with connect() as connection:
        employee, cfg = authenticate(h, connection, data)
        if not employee: return
        current = employee_today(connection, employee, cfg)
        kind = data.get("kind")
        if kind not in current["next"]: return h.send_json(409, {"error": "invalid_sequence", **current})
        moment = datetime.now(timezone.utc)
        connection.execute("INSERT INTO punches(employee_id,kind,at,ip) VALUES(?,?,?,?)", (employee["id"], kind, iso(moment), h.client_ip()))
        result = employee_today(connection, employee, cfg)
    h.send_json(201, {"recorded": kind, "time": local_time(iso(moment), ZoneInfo(cfg["timezone"])), **result})

# ---------- admin side ----------

def public_settings(cfg):
    return {"office_networks": networks(cfg), "work_start": cfg["work_start"], "work_end": cfg["work_end"],
            "workdays": sorted(workdays(cfg)), "late_tolerance": int(cfg["late_tolerance"]), "timezone": cfg["timezone"]}

def admin_overview(h, query):
    with connect() as connection:
        cfg = load_settings(connection); tz = ZoneInfo(cfg["timezone"]); now = datetime.now(timezone.utc).astimezone(tz)
        try: day = date.fromisoformat(query.get("date", [""])[0])
        except ValueError: day = now.date()
        employees = connection.execute("SELECT id,name,active,created_at FROM employees ORDER BY active DESC, name COLLATE NOCASE").fetchall()
        rows = punches_between(connection, *day_bounds(day, tz))
    grouped = {}
    for row in rows: grouped.setdefault(row["employee_id"], []).append(row)
    day_rows = []
    for employee in employees:
        punches = grouped.get(employee["id"], [])
        if not employee["active"] and not punches: continue
        day_rows.append({"employee_id": employee["id"], "name": employee["name"], **summarize(punches, day, tz, cfg, now, created_day(employee, tz)),
                         "punches": [{"id": p["id"], "kind": p["kind"], "time": local_time(p["at"], tz), "manual": bool(p["manual"]), "note": p["note"]} for p in punches]})
    ip = h.client_ip()
    h.send_json(200, {"date": day.isoformat(), "today": now.date().isoformat(), "settings": public_settings(cfg), "current_ip": ip,
                      "on_office_network": bool(networks(cfg)) and office_allowed(ip, cfg),
                      "employees": [{"id": e["id"], "name": e["name"], "active": bool(e["active"])} for e in employees], "day": day_rows})

def month_report(connection, month):
    cfg = load_settings(connection); tz = ZoneInfo(cfg["timezone"]); now = datetime.now(timezone.utc).astimezone(tz)
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    employees = connection.execute("SELECT id,name,active,created_at FROM employees ORDER BY name COLLATE NOCASE").fetchall()
    grouped = {}
    for row in punches_between(connection, day_bounds(first, tz)[0], day_bounds(last, tz)[1]):
        grouped.setdefault((row["employee_id"], datetime.fromisoformat(row["at"]).astimezone(tz).date()), []).append(row)
    report = []
    for employee in employees:
        created, days, day = created_day(employee, tz), [], first
        while day <= min(last, now.date()):
            summary = summarize(grouped.get((employee["id"], day), []), day, tz, cfg, now, created)
            if summary["status"] != "off": days.append({"date": day.isoformat(), **summary})
            day += timedelta(days=1)
        if not employee["active"] and not any(item["first_in"] for item in days): continue
        report.append({"employee_id": employee["id"], "name": employee["name"], "days": days,
                       "worked": sum(item["worked"] for item in days), "breaks": sum(item["breaks"] for item in days),
                       "present_days": sum(1 for item in days if item["first_in"]), "late_count": sum(1 for item in days if item["late"]),
                       "late_minutes": sum(item["late"] for item in days), "absences": sum(1 for item in days if item["status"] == "absent"),
                       "missing_out": sum(1 for item in days if item["missing_out"])})
    return report

def requested_month(query):
    month = query.get("month", [""])[0]
    return month if re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month) else None

def admin_month(h, query):
    month = requested_month(query)
    if not month: return h.send_json(400, {"error": "invalid_month"})
    with connect() as connection: report = month_report(connection, month)
    h.send_json(200, {"month": month, "employees": report})

def admin_export(h, query):
    month = requested_month(query)
    if not month: return h.send_json(400, {"error": "invalid_month"})
    with connect() as connection: report = month_report(connection, month)
    stream = io.StringIO(); writer = csv.writer(stream, delimiter=";")
    writer.writerow(["Salarié", "Date", "Statut", "Arrivée", "Départ", "Pauses (min)", "Travaillé", "Retard (min)"])
    for employee in report:
        for item in employee["days"]:
            writer.writerow([csv_safe(employee["name"]), item["date"], STATUS_LABELS[item["status"]], item["first_in"], item["last_out"], item["breaks"], hours_text(item["worked"]), item["late"]])
        writer.writerow([csv_safe(employee["name"]), "TOTAL", f'{employee["present_days"]} jours présents, {employee["absences"]} absences', "", "", employee["breaks"], hours_text(employee["worked"]), employee["late_minutes"]])
        writer.writerow([])
    body = stream.getvalue().encode("utf-8-sig")
    h._json_response = True
    h.send_response(200); h.send_header("Content-Type", "text/csv; charset=utf-8"); h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Disposition", f'attachment; filename="pointage-{month}.csv"'); h.send_header("Content-Length", str(len(body))); h.end_headers(); h.wfile.write(body)

def admin_settings(h, query):
    data = h.read_json()
    if data is None: return h.send_json(400, {"error": "invalid_json"})
    work_start, work_end, tz = str(data.get("work_start", "")), str(data.get("work_end", "")), str(data.get("timezone", DEFAULTS["timezone"]))
    if tz not in TIMEZONES: return h.send_json(400, {"error": "invalid_settings"})
    if not TIME_RE.fullmatch(work_start) or not TIME_RE.fullmatch(work_end) or work_end <= work_start: return h.send_json(400, {"error": "invalid_hours"})
    try:
        tolerance = int(data.get("late_tolerance", 10))
        days = sorted({int(item) for item in data.get("workdays", [])})
        nets = [str(ipaddress.ip_network(str(item).strip(), strict=False)) for item in data.get("office_networks", []) if str(item).strip()]
    except (TypeError, ValueError):
        return h.send_json(400, {"error": "invalid_settings"})
    if not 0 <= tolerance <= 120 or any(not 0 <= item <= 6 for item in days) or len(nets) > 10: return h.send_json(400, {"error": "invalid_settings"})
    values = {"timezone": tz, "work_start": work_start, "work_end": work_end, "late_tolerance": str(tolerance), "workdays": ",".join(map(str, days)), "office_networks": ",".join(dict.fromkeys(nets))}
    with connect() as connection:
        connection.executemany("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", values.items())
    h.send_json(200, {"ok": True})

def valid_name(value):
    name = str(value or "").strip()
    return name if 2 <= len(name) <= 60 else None

def valid_pin(value):
    pin = str(value or "")
    return pin if re.fullmatch(r"\d{4,8}", pin) else None

def admin_create_employee(h, query):
    data = h.read_json() or {}
    name, pin = valid_name(data.get("name")), valid_pin(data.get("pin"))
    if not name: return h.send_json(400, {"error": "invalid_name"})
    if not pin: return h.send_json(400, {"error": "invalid_pin"})
    salt = secrets.token_bytes(16)
    with connect() as connection:
        connection.execute("INSERT INTO employees(name,salt,pin_hash,created_at) VALUES(?,?,?,?)", (name, salt.hex(), pin_hash(pin, salt), iso(datetime.now(timezone.utc))))
    h.send_json(201, {"ok": True})

def admin_update_employee(h, employee_id):
    data = h.read_json() or {}
    updates = {}
    if "name" in data:
        if not valid_name(data["name"]): return h.send_json(400, {"error": "invalid_name"})
        updates["name"] = valid_name(data["name"])
    if "pin" in data:
        if not valid_pin(data["pin"]): return h.send_json(400, {"error": "invalid_pin"})
        salt = secrets.token_bytes(16); updates["salt"] = salt.hex(); updates["pin_hash"] = pin_hash(data["pin"], salt)
    if "active" in data: updates["active"] = 1 if data["active"] else 0
    if not updates: return h.send_json(400, {"error": "nothing_to_update"})
    with connect() as connection:
        result = connection.execute("UPDATE employees SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?", (*updates.values(), employee_id))
    if result.rowcount == 0: return h.send_json(404, {"error": "not_found"})
    if "pin_hash" in updates: PIN_FAILURES.pop(f"employee:{employee_id}", None)
    h.send_json(200, {"ok": True})

def admin_add_punch(h, query):
    data = h.read_json() or {}
    kind, note, clock = data.get("kind"), str(data.get("note", "")).strip()[:200], str(data.get("time", ""))
    if kind not in KIND_LABELS or not TIME_RE.fullmatch(clock): return h.send_json(400, {"error": "invalid_punch"})
    try: employee_id, day = int(data.get("employee_id")), date.fromisoformat(str(data.get("date", "")))
    except (TypeError, ValueError): return h.send_json(400, {"error": "invalid_punch"})
    with connect() as connection:
        tz = ZoneInfo(load_settings(connection)["timezone"])
        if not connection.execute("SELECT 1 FROM employees WHERE id=?", (employee_id,)).fetchone(): return h.send_json(404, {"error": "not_found"})
        moment = datetime.combine(day, datetime.strptime(clock, "%H:%M").time(), tz)
        connection.execute("INSERT INTO punches(employee_id,kind,at,ip,manual,note) VALUES(?,?,?,?,1,?)", (employee_id, kind, iso(moment), "admin", note))
    h.send_json(201, {"ok": True})

def admin_delete_punch(h, punch_id):
    with connect() as connection:
        result = connection.execute("DELETE FROM punches WHERE id=?", (punch_id,))
    if result.rowcount == 0: return h.send_json(404, {"error": "not_found"})
    h.send_json(200, {"ok": True})
