"""
Дерекқормен жұмыс модулі (SQLite).

Барлық SQL сұраулары параметрлермен (?) жазылған — SQL-инъекциядан қорғаныс.
Бизнес-ережелер queue_logic.py ішінде, бұл модуль тек оларды деректерге қолданады.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from . import service as ql

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT    NOT NULL UNIQUE,          -- талон префиксі: A, B, C ...
    name_kk      TEXT    NOT NULL,
    name_ru      TEXT    NOT NULL,
    avg_minutes  REAL    NOT NULL DEFAULT 5 CHECK (avg_minutes > 0),
    is_active    INTEGER NOT NULL DEFAULT 1
);

-- Барлық пайдаланушылар: студент, әдіскер, декан орынбасары, декан (әкімші)
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,         -- студентте = ЖСН (ИИН)
    password_hash TEXT    NOT NULL,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('student','dekanat','deputy','admin')),
    student_id    TEXT    UNIQUE,                  -- студенттің ЖСН-і (ескі аккаунттарда — студенттік ID)
    group_name    TEXT    NOT NULL DEFAULT '',
    window_no     TEXT,                            -- қызметкердің аудиториясы (мысалы, 305 не 214А)
    is_active     INTEGER NOT NULL DEFAULT 1,      -- 0 = растауды күтуде / бұғатталған
    on_duty       INTEGER NOT NULL DEFAULT 0,      -- терезе ашық па
    on_break      INTEGER NOT NULL DEFAULT 0,      -- қызметкер үзілісте ме
    created_at    TEXT    NOT NULL,
    phone         TEXT    NOT NULL DEFAULT '',     -- профиль: +7 7xx xxx xx xx
    gender        TEXT    NOT NULL DEFAULT '',     -- '', 'male', 'female'
    email         TEXT    NOT NULL DEFAULT '',
    avatar        TEXT    NOT NULL DEFAULT ''      -- instance/avatars ішіндегі файл атауы
);

-- Ерекше күндер: декан белгілеген демалыс/мереке немесе қысқартылған жұмыс күні
CREATE TABLE IF NOT EXISTS day_overrides (
    day        TEXT PRIMARY KEY,                   -- YYYY-MM-DD
    kind       TEXT NOT NULL CHECK (kind IN ('holiday','short')),
    open_at    TEXT,                               -- HH:MM, тек 'short'
    close_at   TEXT,
    note       TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

-- Хабарландырулар (басты бетте, студент кабинетінде және таблода көрсетіледі)
CREATE TABLE IF NOT EXISTS announcements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    start_day  TEXT NOT NULL,                      -- YYYY-MM-DD
    end_day    TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

-- Жүйе баптаулары (кілт — мән), мысалы жұмыс кестесі JSON түрінде
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Деканат қызметкері қандай қызметтерді көрсетеді (көп-көпке байланыс)
CREATE TABLE IF NOT EXISTS user_services (
    user_id    INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, service_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       TEXT    NOT NULL,                 -- A-007
    seq          INTEGER NOT NULL,
    day          TEXT    NOT NULL,                 -- YYYY-MM-DD
    service_id   INTEGER NOT NULL REFERENCES services(id),
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- талон иесі (студент)
    full_name    TEXT    NOT NULL,
    student_id   TEXT    NOT NULL,
    group_name   TEXT    NOT NULL DEFAULT '',
    priority     INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'waiting'
                 CHECK (status IN ('waiting','called','done','no_show','cancelled')),
    token        TEXT    NOT NULL UNIQUE,          -- талон бетіне жеке сілтеме
    operator_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    window_no    TEXT,                     -- шақырылған аудитория
    recall_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    called_at    TEXT,
    finished_at  TEXT,
    UNIQUE (day, service_id, seq)
);

-- Өзгерістер журналы: кім, қашан, не істеді (әкімші түзетулері осында жазылады)
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT    NOT NULL,
    details    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_queue ON tickets(day, service_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, day);
"""

TS_FMT = "%Y-%m-%d %H:%M:%S"


def ts(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def parse_ts(value: str | None) -> datetime | None:
    return datetime.strptime(value, TS_FMT) if value else None


# ---------------------------------------------------------------------------
# Қосылым және бастапқы деректер
# ---------------------------------------------------------------------------
def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False,
                           timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # оқу мен жазу бір-біріне кедергі жасамайды
    return conn


PROFILE_COLUMNS = ("phone", "gender", "email", "avatar")


def init_db(conn: sqlite3.Connection) -> None:
    _migrate_users(conn)
    conn.executescript(SCHEMA)
    _add_profile_columns(conn)
    _add_security_columns(conn)
    _add_service_en(conn)
    _add_booking_column(conn)


def _add_profile_columns(conn: sqlite3.Connection) -> None:
    """Ескі дерекқорға профиль бағандарын (телефон, жыныс, e-mail, сурет) қосады."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for col in PROFILE_COLUMNS:
        if col not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")


def _add_security_columns(conn: sqlite3.Connection) -> None:
    """Қалпына келтіру коды (хэші) мен «құпиясөзді ауыстыру міндетті» белгісі."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "recovery_hash" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN recovery_hash TEXT NOT NULL DEFAULT ''")
    if "must_change" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0")


SERVICE_NAMES_EN = {"A": "Certificate", "B": "Submitting an application",
                    "C": "Academic leave / transfer", "D": "Retake", "E": "Transcript / documents",
                    "F": "Signing an application"}


def _add_service_en(conn: sqlite3.Connection) -> None:
    """Қызметтердің ағылшынша атауы (бос болса — орысшасы көрсетіледі)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(services)")}
    if "name_en" not in cols:
        conn.execute("ALTER TABLE services ADD COLUMN name_en TEXT NOT NULL DEFAULT ''")
    for code, name in SERVICE_NAMES_EN.items():
        conn.execute("UPDATE services SET name_en=? WHERE code=? AND name_en=''", (name, code))


def _migrate_users(conn: sqlite3.Connection) -> None:
    """Ескі дерекқорды жаңартады: 'deputy' рөлі мен on_break бағанын қосады.

    SQLite CHECK шектеуін өзгертуге мүмкіндік бермейді, сондықтан кесте қайта құрылады:
    жаңа кесте жасалады, деректер көшіріледі, ескісі өшіріледі. Басқа кестелердегі
    «REFERENCES users» сілтемелері атауы бойынша жаңа кестені көрсетеді.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if row is None or "'deputy'" in row[0]:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "on_break" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN on_break INTEGER NOT NULL DEFAULT 0")
        # бағанды қосқаннан кейін кесте сипаттамасын қайта оқимыз (ол жаңарды)
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    new_sql = row[0].replace("CREATE TABLE users", "CREATE TABLE users_new", 1)
    new_sql = new_sql.replace("('student','dekanat','admin')", "('student','dekanat','deputy','admin')")
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(new_sql)
        conn.execute("INSERT INTO users_new SELECT * FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------------------
# Баптаулар: жұмыс кестесі
# ---------------------------------------------------------------------------
def _add_booking_column(conn: sqlite3.Connection) -> None:
    """Алдын ала брондалған талонның уақыты (кәдімгі талонда — NULL)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tickets)")}
    if "booked_at" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN booked_at TEXT")


# Брондалған талон уақыты келгенге дейін кезекке кірмейді
DUE = "(booked_at IS NULL OR booked_at <= ?)"
DUE_T = "(t.booked_at IS NULL OR t.booked_at <= ?)"


def get_queue_limit(conn) -> int:
    """Нақты кезекте бір уақытта күте алатын студенттер саны (0 — шектеусіз)."""
    row = conn.execute("SELECT value FROM settings WHERE key='queue_limit'").fetchone()
    return int(row[0]) if row and str(row[0]).isdigit() else ql.DEFAULT_QUEUE_LIMIT


def set_queue_limit(conn, actor_id: int, value, now: datetime) -> None:
    _require_manager(conn, actor_id)
    text = str(value if value is not None else "").strip()
    if not text.isdigit() or int(text) > 500:
        raise ql.QueueError("err_queue_limit")
    conn.execute("INSERT INTO settings (key, value) VALUES ('queue_limit', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(text)),))
    log(conn, actor_id, "queue_limit", text, now)


def get_schedule(conn) -> ql.Schedule:
    row = conn.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
    if row is None:
        return ql.DEFAULT_SCHEDULE
    try:
        return ql.schedule_from_dict(json.loads(row[0]))
    except (ValueError, KeyError, ql.QueueError):
        return ql.DEFAULT_SCHEDULE  # бұзылған жазба болса — әдепкі кесте


def save_schedule(conn, actor_id: int, schedule: ql.Schedule, now: datetime) -> None:
    _require_manager(conn, actor_id)
    data = ql.schedule_to_dict(schedule)
    conn.execute("INSERT INTO settings (key, value) VALUES ('schedule', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (json.dumps(data, ensure_ascii=False),))
    log(conn, actor_id, "schedule", json.dumps(data, ensure_ascii=False), now)


# ---------------------------------------------------------------------------
# Ерекше күндер және хабарландырулар
# ---------------------------------------------------------------------------
def get_overrides(conn) -> dict:
    """Барлық ерекше күндер: {date: DayOverride}."""
    out = {}
    for r in conn.execute("SELECT * FROM day_overrides"):
        try:
            if r["kind"] == ql.SHORT:
                o = ql.build_override(r["day"], r["kind"], r["open_at"], r["close_at"], r["note"])
            else:
                o = ql.build_override(r["day"], r["kind"], note=r["note"])
        except ql.QueueError:
            continue  # бұзылған жазба есепке алынбайды
        out[o.day] = o
    return out


def list_overrides(conn, from_day: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM day_overrides WHERE day >= ? ORDER BY day",
                        (from_day,)).fetchall()


def save_override(conn, actor_id: int, o: ql.DayOverride, now: datetime) -> None:
    _require_manager(conn, actor_id)
    fmt = lambda t: t.strftime("%H:%M") if t else None
    conn.execute(
        "INSERT INTO day_overrides (day, kind, open_at, close_at, note, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(day) DO UPDATE SET kind=excluded.kind, "
        "open_at=excluded.open_at, close_at=excluded.close_at, note=excluded.note, "
        "created_by=excluded.created_by, created_at=excluded.created_at",
        (o.day.isoformat(), o.kind, fmt(o.open_at), fmt(o.close_at), o.note, actor_id, ts(now)))
    log(conn, actor_id, "day_override", f"{o.day} {o.kind} {fmt(o.open_at) or ''}-{fmt(o.close_at) or ''}", now)


def delete_override(conn, actor_id: int, day: str, now: datetime) -> None:
    _require_manager(conn, actor_id)
    conn.execute("DELETE FROM day_overrides WHERE day=?", (day,))
    log(conn, actor_id, "day_override_delete", day, now)


def active_announcements(conn, now: datetime) -> list[sqlite3.Row]:
    day = now.strftime("%Y-%m-%d")
    return conn.execute("SELECT * FROM announcements WHERE start_day <= ? AND end_day >= ? "
                        "ORDER BY id DESC", (day, day)).fetchall()


def list_announcements(conn, now: datetime) -> list[sqlite3.Row]:
    """Басқару панелі үшін: мерзімі өтпеген хабарландырулар."""
    return conn.execute("SELECT * FROM announcements WHERE end_day >= ? ORDER BY start_day, id",
                        (now.strftime("%Y-%m-%d"),)).fetchall()


def add_announcement(conn, actor_id: int, a: ql.Announcement, now: datetime) -> int:
    _require_manager(conn, actor_id)
    aid = conn.execute("INSERT INTO announcements (text, start_day, end_day, created_by, created_at) "
                       "VALUES (?,?,?,?,?)", (a.text, a.start.isoformat(), a.end.isoformat(),
                                              actor_id, ts(now))).lastrowid
    log(conn, actor_id, "announcement", a.text[:80], now)
    return aid


def delete_announcement(conn, actor_id: int, announcement_id: int, now: datetime) -> None:
    _require_manager(conn, actor_id)
    conn.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
    log(conn, actor_id, "announcement_delete", str(announcement_id), now)


def _require_manager(conn, actor_id: int) -> sqlite3.Row:
    actor = get_user(conn, actor_id)
    if actor is None or actor["role"] not in ql.MANAGER_ROLES or not actor["is_active"]:
        raise ql.QueueError("err_forbidden")
    return actor


# Код (A, B ...) тек талон нөмірінде қолданылады (A-007); сайтта қызметтің атауы ғана көрінеді.
# Соңғы сан — бір студентті қабылдаудың болжамды уақыты (минут).
DEFAULT_SERVICES = [
    ("A", "Анықтама алу", "Получение справки", 3),
    ("B", "Өтініш тапсыру", "Подача заявления", 5),
    ("C", "Академиялық демалыс / ауысу", "Академ. отпуск / перевод", 12),
    ("D", "Пәндерді қайта тапсыру (Retake)", "Пересдача (Retake)", 10),
    ("E", "Транскрипт / құжаттар", "Транскрипт / документы", 7),
    ("F", "Өтінішке қол қою", "Подпись заявления", 1),
]
OLD_SERVICE_MINUTES = {"A": 4, "B": 6, "D": 8}  # бұрынғы әдепкі мәндер (жаңарту үшін)
DEMO_STUDENT_IIN = "030512501238"  # ойдан алынған, бірақ бақылау цифры дұрыс ЖСН

# Демо-аккаунттар (логин, құпиясөз, аты-жөні, рөл, қосымша)
DEMO_USERS = [
    ("admin", "Admin2026", "А. Нұрланов", ql.ADMIN, {"window_no": 1}),
    ("zamdekan", "Deputy2026", "Р. Әбенова", ql.DEPUTY,
     {"window_no": 4, "service_codes": ["A", "B", "C", "D", "E", "F"]}),
    ("dekanat1", "Dekanat2026", "Әдіскер Ж. Сейітова", ql.DEKANAT,
     {"window_no": 2, "service_codes": ["A", "B", "E", "F"]}),
    ("dekanat2", "Dekanat2026", "Әдіскер Б. Омаров", ql.DEKANAT,
     {"window_no": 3, "service_codes": ["B", "C", "D"]}),
    (DEMO_STUDENT_IIN, "Student2026", "Айгерім Сәрсенова", ql.STUDENT,
     {"student_id": DEMO_STUDENT_IIN, "group_name": "ИС-21-1"}),
]


def seed(conn: sqlite3.Connection, now: datetime | None = None) -> None:
    """Бос дерекқорға демо-деректерді қосады (қайта шақыруға болады)."""
    now = now or datetime.now()
    if conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO services (code, name_kk, name_ru, avg_minutes) VALUES (?,?,?,?)",
            DEFAULT_SERVICES)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        for username, password, name, role, extra in DEMO_USERS:
            extra = dict(extra)
            if role == ql.ADMIN:
                extra["service_codes"] = [s[0] for s in DEFAULT_SERVICES]
            create_user(conn, username, password, name, role, now=now, **extra)
    elif not conn.execute("SELECT 1 FROM users WHERE role='deputy'").fetchone():
        # Ескі демо-дерекқорға декан орынбасарының демо-аккаунтын қосу
        username, password, name, role, extra = DEMO_USERS[1]
        if not conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            create_user(conn, username, password, name, role, now=now, **extra)
    _update_services_v2(conn)
    _add_service_en(conn)
    _drop_short_breaks(conn)


def _drop_short_breaks(conn: sqlite3.Connection) -> None:
    """Сақталған кестеден қысқа үзілістерді бір рет алып тастайды (тапсырыс берушінің талабы)."""
    if conn.execute("SELECT 1 FROM settings WHERE key='no_short_breaks'").fetchone():
        return
    row = conn.execute("SELECT value FROM settings WHERE key='schedule'").fetchone()
    if row is not None:
        data = json.loads(row[0])
        data["breaks"] = ""
        conn.execute("UPDATE settings SET value=? WHERE key='schedule'",
                     (json.dumps(data, ensure_ascii=False),))
    conn.execute("INSERT INTO settings (key, value) VALUES ('no_short_breaks', '1')")


def _update_services_v2(conn: sqlite3.Connection) -> None:
    """Бұрынғы дерекқорға «Өтінішке қол қою» (1 мин) қызметін қосып, әдепкі уақыттарды
    жаңартады. Бір рет қана орындалады: декан кейін өзгертсе, қайта жазылмайды."""
    if conn.execute("SELECT 1 FROM settings WHERE key='services_v2'").fetchone():
        return
    for code, minutes in OLD_SERVICE_MINUTES.items():
        new = next(s[3] for s in DEFAULT_SERVICES if s[0] == code)
        conn.execute("UPDATE services SET avg_minutes=? WHERE code=? AND avg_minutes=?",
                     (new, code, minutes))
    code, name_kk, name_ru, minutes = DEFAULT_SERVICES[-1]
    if not conn.execute("SELECT 1 FROM services WHERE code=? OR name_kk=?", (code, name_kk)).fetchone():
        sid = conn.execute("INSERT INTO services (code, name_kk, name_ru, avg_minutes) VALUES (?,?,?,?)",
                           (code, name_kk, name_ru, minutes)).lastrowid
        # «Өтініш тапсыру» қызметін көрсететін қызметкерлер қол қоюды да қабылдайды
        conn.execute("INSERT OR IGNORE INTO user_services (user_id, service_id) "
                     "SELECT us.user_id, ? FROM user_services us JOIN services s ON s.id=us.service_id "
                     "WHERE s.code='B'", (sid,))
    conn.execute("INSERT INTO settings (key, value) VALUES ('services_v2', '1')")


def log(conn, user_id: int | None, action: str, details: str, now: datetime) -> None:
    conn.execute("INSERT INTO audit_log (user_id, action, details, created_at) VALUES (?,?,?,?)",
                 (user_id, action, details[:500], ts(now)))


def list_audit(conn, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        "ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()


# ---------------------------------------------------------------------------
# Пайдаланушылар
# ---------------------------------------------------------------------------
def create_user(conn, username: str, password: str, full_name: str, role: str, *,
                now: datetime, student_id: str | None = None, group_name: str = "",
                window_no: int | None = None, is_active: bool = True,
                service_codes=()) -> int:
    if role not in ql.ROLES:
        raise ql.QueueError("err_role")
    if ql.validate_password(password):
        raise ql.QueueError("err_password_weak")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ql.QueueError("err_username_taken")
    if student_id and conn.execute("SELECT 1 FROM users WHERE student_id=?",
                                   (student_id,)).fetchone():
        raise ql.QueueError("err_username_taken")
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role, student_id, group_name, "
        "window_no, is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (username, generate_password_hash(password), full_name, role, student_id,
         group_name, window_no, 1 if is_active else 0, ts(now)))
    uid = cur.lastrowid
    set_user_services_by_code(conn, uid, service_codes)
    return uid


def register(conn, reg: ql.Registration, now: datetime) -> int:
    """Өздігінен тіркелу. Студент бірден белсенді; қызметкерлер (әдіскер, орынбасар, декан)
    растағанша кіре алмайды. Декан өтінімін тек декан растай алады (can_manage_user)."""
    active = reg.role == ql.STUDENT
    uid = create_user(conn, reg.username, reg.password, reg.full_name, reg.role, now=now,
                      student_id=reg.student_id, group_name=reg.group_name,
                      is_active=active)
    log(conn, uid, "register", f"{reg.role}:{reg.username}", now)
    return uid


def set_user_services_by_code(conn, user_id: int, codes) -> None:
    for code in codes:
        row = conn.execute("SELECT id FROM services WHERE code=?", (code,)).fetchone()
        if row:
            conn.execute("INSERT OR IGNORE INTO user_services VALUES (?,?)", (user_id, row["id"]))


def authenticate(conn, username: str, password: str,
                 role: str | None = None) -> tuple[sqlite3.Row | None, str | None]:
    """(пайдаланушы, қате_кілті) қайтарады. Құпиясөз қате болса — бірдей хабар."""
    row = conn.execute("SELECT * FROM users WHERE username=?",
                       ((username or "").strip().lower(),)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        return None, "err_login"
    if role and row["role"] != role:
        return None, "err_wrong_role"
    if not row["is_active"]:
        return None, "err_inactive"
    return row, None


def get_user(conn, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def list_users(conn, role: str | None = None) -> list[sqlite3.Row]:
    if role:
        return conn.execute("SELECT * FROM users WHERE role=? ORDER BY is_active, id",
                            (role,)).fetchall()
    return conn.execute(
        "SELECT * FROM users ORDER BY is_active, "
        "CASE role WHEN 'admin' THEN 0 WHEN 'deputy' THEN 1 WHEN 'dekanat' THEN 2 ELSE 3 END, id").fetchall()


def count_pending(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE is_active=0").fetchone()[0]


def set_on_duty(conn, user_id: int, on: bool) -> None:
    """Кіргенде терезе ашылады, шыққанда жабылады (үзіліс те тоқтайды)."""
    conn.execute("UPDATE users SET on_duty=?, on_break=0 WHERE id=?", (1 if on else 0, user_id))


def set_break(conn, user_id: int, on: bool, now: datetime) -> None:
    """Қызметкердің жеке үзілісі. Ағымдағы студентті аяқтамай үзіліске шығуға болмайды."""
    user = get_user(conn, user_id)
    if user is None or user["role"] not in ql.STAFF_ROLES:
        raise ql.QueueError("err_forbidden")
    if on and conn.execute("SELECT 1 FROM tickets WHERE operator_id=? AND status='called'",
                           (user_id,)).fetchone():
        raise ql.QueueError("err_finish_current")
    conn.execute("UPDATE users SET on_break=? WHERE id=?", (1 if on else 0, user_id))
    log(conn, user_id, "break_start" if on else "break_end", f"window={user['window_no']}", now)


def user_service_ids(conn, user_id: int) -> set[int]:
    return {r[0] for r in conn.execute(
        "SELECT service_id FROM user_services WHERE user_id=?", (user_id,))}


def change_password(conn, user_id: int, old: str, new: str, new2: str, now: datetime) -> None:
    user = get_user(conn, user_id)
    if user is None or not check_password_hash(user["password_hash"], old or ""):
        raise ql.QueueError("err_old_password")
    errors = ql.validate_password(new, new2)
    if errors:
        raise ql.QueueError(errors[0])
    conn.execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                 (generate_password_hash(new), user_id))
    log(conn, user_id, "change_password", "", now)


def set_recovery_code(conn, user_id: int, now: datetime) -> str:
    """Жаңа қалпына келтіру кодын жасап, тек хэшін сақтайды; кодтың өзін бір рет қайтарады."""
    code = ql.generate_recovery_code()
    conn.execute("UPDATE users SET recovery_hash=? WHERE id=?",
                 (generate_password_hash(ql.normalize_recovery_code(code)), user_id))
    log(conn, user_id, "recovery_code", "", now)
    return code


def reset_with_recovery(conn, username: str, code: str, new: str, new2: str, now: datetime) -> str:
    """Логин + қалпына келтіру коды арқылы жаңа құпиясөз. Код бір реттік: жаңасын қайтарады."""
    user = conn.execute("SELECT * FROM users WHERE username=?",
                        ((username or "").strip().lower(),)).fetchone()
    ok = (user is not None and user["recovery_hash"] and user["is_active"]
          and check_password_hash(user["recovery_hash"], ql.normalize_recovery_code(code)))
    if not ok:
        raise ql.QueueError("err_recovery")  # логин не код — қайсысы қате екенін айтпаймыз
    errors = ql.validate_password(new, new2)
    if errors:
        raise ql.QueueError(errors[0])
    conn.execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                 (generate_password_hash(new), user["id"]))
    log(conn, user["id"], "reset_by_code", user["username"], now)
    return set_recovery_code(conn, user["id"], now)


def force_set_password(conn, username: str, password: str, now: datetime) -> None:
    """Консоль арқылы құпиясөзді қалпына келтіру (flask set-password). Аккаунт белсенді болады."""
    user = conn.execute("SELECT * FROM users WHERE username=?",
                        ((username or "").strip().lower(),)).fetchone()
    if user is None:
        raise ql.QueueError("err_not_found")
    errors = ql.validate_password(password)
    if errors:
        raise ql.QueueError(errors[0])
    conn.execute("UPDATE users SET password_hash=?, is_active=1 WHERE id=?",
                 (generate_password_hash(password), user["id"]))
    log(conn, user["id"], "reset_password_cli", user["username"], now)


def update_profile(conn, user_id: int, data: dict, now: datetime) -> None:
    """Профиль: телефон, жыныс, e-mail, ал администраторда аты-жөні де (тексерілген деректер)."""
    conn.execute("UPDATE users SET phone=?, gender=?, email=? WHERE id=?",
                 (data["phone"], data["gender"], data["email"], user_id))
    if data.get("full_name"):
        conn.execute("UPDATE users SET full_name=? WHERE id=?", (data["full_name"], user_id))
    if "group_name" in data:
        conn.execute("UPDATE users SET group_name=? WHERE id=?", (data["group_name"], user_id))
    if "window_no" in data:  # қызметкер өз аудиториясын жазады
        conn.execute("UPDATE users SET window_no=? WHERE id=?", (data["window_no"], user_id))
    log(conn, user_id, "profile", "", now)


def set_avatar(conn, user_id: int, filename: str) -> str:
    """Жаңа сурет атауын жазып, ескісінің атауын қайтарады (оны файлдан өшіру үшін)."""
    old = get_user(conn, user_id)["avatar"]
    conn.execute("UPDATE users SET avatar=? WHERE id=?", (filename, user_id))
    return old


# ---------------- Әкімші / декан орынбасары: аккаунттарды басқару ----------------
def _managed_target(conn, actor_id: int, user_id: int, new_role: str | None = None):
    """Әрекет жасаушының құқығын тексеріп, өзгертілетін аккаунтты қайтарады."""
    actor = _require_manager(conn, actor_id)
    target = get_user(conn, user_id)
    if target is None:
        raise ql.QueueError("err_not_found")
    if not ql.can_manage_user(actor["role"], target["role"], new_role):
        raise ql.QueueError("err_forbidden")
    return target


def _active_admins(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                        ).fetchone()[0]


def _protect_last_admin(conn, target, admin_id: int) -> None:
    """Әкімші өзін бұғаттай/өшіре алмайды және соңғы әкімшіні жоюға болмайды."""
    if target["id"] == admin_id:
        raise ql.QueueError("err_self")
    if target["role"] == ql.ADMIN and target["is_active"] and _active_admins(conn) <= 1:
        raise ql.QueueError("err_last_admin")


def admin_set_active(conn, admin_id: int, user_id: int, active: bool, now: datetime) -> None:
    target = _managed_target(conn, admin_id, user_id)
    if not active:
        _protect_last_admin(conn, target, admin_id)
    conn.execute("UPDATE users SET is_active=?, on_duty=CASE WHEN ?=0 THEN 0 ELSE on_duty END "
                 "WHERE id=?", (1 if active else 0, 1 if active else 0, user_id))
    log(conn, admin_id, "activate" if active else "block", target["username"], now)


def admin_set_role(conn, admin_id: int, user_id: int, role: str, now: datetime) -> None:
    if role not in ql.ROLES:
        raise ql.QueueError("err_role")
    target = _managed_target(conn, admin_id, user_id, role)
    if role == target["role"]:
        return
    if target["role"] == ql.ADMIN:
        _protect_last_admin(conn, target, admin_id)
    if role == ql.STUDENT and not target["student_id"]:
        raise ql.QueueError("err_student_id")  # студент рөліне ID қажет
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    log(conn, admin_id, "set_role", f"{target['username']}: {target['role']} -> {role}", now)


def admin_reset_password(conn, admin_id: int, user_id: int, new: str, now: datetime) -> None:
    target = _managed_target(conn, admin_id, user_id)
    errors = ql.validate_password(new)
    if errors:
        raise ql.QueueError(errors[0])
    # Уақытша құпиясөз: пайдаланушы келесі кіргенде оны өзі ауыстыруы міндетті
    conn.execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?",
                 (generate_password_hash(new), user_id))
    log(conn, admin_id, "reset_password", target["username"], now)


def admin_update_staff(conn, admin_id: int, user_id: int, window_no, service_ids,
                       now: datetime) -> None:
    target = _managed_target(conn, admin_id, user_id)
    window = ql.validate_room(window_no)
    valid = {s["id"] for s in list_services(conn, active_only=False)}
    ids = {int(i) for i in service_ids if str(i).isdigit() and int(i) in valid}
    conn.execute("UPDATE users SET window_no=? WHERE id=?", (window, user_id))
    conn.execute("DELETE FROM user_services WHERE user_id=?", (user_id,))
    conn.executemany("INSERT INTO user_services VALUES (?,?)", [(user_id, i) for i in ids])
    log(conn, admin_id, "update_staff", f"{target['username']}: window={window}, services={sorted(ids)}", now)


def admin_delete_user(conn, admin_id: int, user_id: int, now: datetime) -> None:
    target = _managed_target(conn, admin_id, user_id)
    _protect_last_admin(conn, target, admin_id)
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))  # талондар сақталады (user_id=NULL)
    log(conn, admin_id, "delete_user", target["username"], now)


# ---------------------------------------------------------------------------
# Қызметтер
# ---------------------------------------------------------------------------
def list_services(conn, active_only: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT id, code, name_kk, name_ru, COALESCE(NULLIF(name_en, ''), name_ru) AS name_en, avg_minutes, is_active FROM services"
    if active_only:
        sql += " WHERE is_active = 1"
    return conn.execute(sql + " ORDER BY code").fetchall()


def get_service(conn, service_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT id, code, name_kk, name_ru, COALESCE(NULLIF(name_en, ''), name_ru) AS name_en, avg_minutes, is_active FROM services WHERE id=?", (service_id,)).fetchone()


def _validate_service(code: str, name_kk: str, name_ru: str, avg) -> tuple[str, str, str, float]:
    code = (code or "").strip().upper()
    name_kk, name_ru = (name_kk or "").strip(), (name_ru or "").strip()
    if not code.isalpha() or not 1 <= len(code) <= 2:
        raise ql.QueueError("err_bad_service_code")
    if not (2 <= len(name_kk) <= 80 and 2 <= len(name_ru) <= 80):
        raise ql.QueueError("err_service_name")
    try:
        avg = float(avg)
        if not 0 < avg <= 120:
            raise ValueError
    except (TypeError, ValueError):
        raise ql.QueueError("err_avg")
    return code, name_kk, name_ru, avg


def admin_save_service(conn, admin_id: int, service_id: int | None, code, name_kk, name_ru,
                       avg, active: bool, now: datetime) -> int:
    _require_manager(conn, admin_id)
    code, name_kk, name_ru, avg = _validate_service(code, name_kk, name_ru, avg)
    dup = conn.execute("SELECT id FROM services WHERE code=?", (code,)).fetchone()
    if dup and dup["id"] != service_id:
        raise ql.QueueError("err_service_code_taken")
    if service_id is None:
        sid = conn.execute(
            "INSERT INTO services (code, name_kk, name_ru, avg_minutes, is_active) "
            "VALUES (?,?,?,?,?)", (code, name_kk, name_ru, avg, 1 if active else 0)).lastrowid
        log(conn, admin_id, "create_service", code, now)
        return sid
    if get_service(conn, service_id) is None:
        raise ql.QueueError("err_not_found")
    conn.execute("UPDATE services SET code=?, name_kk=?, name_ru=?, avg_minutes=?, is_active=? "
                 "WHERE id=?", (code, name_kk, name_ru, avg, 1 if active else 0, service_id))
    log(conn, admin_id, "update_service", f"{code} active={int(active)} avg={avg}", now)
    return service_id


# ---------------------------------------------------------------------------
# Талондар
# ---------------------------------------------------------------------------
MAX_ACTIVE_TICKETS = 3  # бір студенттің бір күндегі белсенді талондарының шегі


def _ticket_service(conn, user, service_id, now: datetime, check_hours: bool) -> sqlite3.Row:
    """Талон беруге бола ма: студент, жұмыс уақыты, қызмет. Болса — қызметті қайтарады."""
    if user is None or user["role"] != ql.STUDENT or not user["is_active"]:
        raise ql.QueueError("err_forbidden")
    if check_hours and not ql.can_take_ticket(now, get_schedule(conn), get_overrides(conn)):
        raise ql.QueueError("err_closed")
    try:
        service_id = int(service_id)
    except (TypeError, ValueError):
        raise ql.QueueError("err_service")
    service = get_service(conn, service_id)
    if service is None or not service["is_active"]:
        raise ql.QueueError("err_service")
    return service


def _check_ticket_limits(conn, day: str, user_id: int, service_id: int) -> None:
    """Бір қызметке бір белсенді талон, барлығы MAX_ACTIVE_TICKETS-тен аспайды."""
    if conn.execute(
            "SELECT 1 FROM tickets WHERE day=? AND user_id=? AND service_id=? "
            "AND status IN ('waiting','called')", (day, user_id, service_id)).fetchone():
        raise ql.QueueError("err_already_in_queue")
    active_total = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE day=? AND user_id=? "
        "AND status IN ('waiting','called')", (day, user_id)).fetchone()[0]
    if active_total >= MAX_ACTIVE_TICKETS:
        raise ql.QueueError("err_too_many")


def create_ticket(conn, user, service_id, now: datetime, priority: bool = False,
                  check_hours: bool = True) -> sqlite3.Row:
    """Студентке жаңа талон береді. Ережелер бұзылса QueueError шығарады."""
    service = _ticket_service(conn, user, service_id, now, check_hours)
    day = now.strftime("%Y-%m-%d")
    conn.execute("BEGIN IMMEDIATE")  # нөмірлер қайталанбауы үшін жазуды бұғаттаймыз
    try:
        _check_ticket_limits(conn, day, user["id"], service["id"])
        _check_queue_limit(conn, day)
        token = _insert_ticket(conn, user, service, day, now, priority=priority, booked=False)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_ticket_by_token(conn, token)


def live_waiting(conn, day: str) -> int:
    """Нақты кезектегі күтушілер (брондалғандар шекке кірмейді)."""
    return conn.execute("SELECT COUNT(*) FROM tickets WHERE day=? AND status='waiting' "
                        "AND booked_at IS NULL", (day,)).fetchone()[0]


def _check_queue_limit(conn, day: str) -> None:
    limit = get_queue_limit(conn)
    if limit and live_waiting(conn, day) >= limit:
        raise ql.QueueError("err_queue_full")


def _insert_ticket(conn, user, service, day: str, created: datetime, priority: bool, booked: bool) -> str:
    """Талонды жазу (транзакция ішінде). Брондауда created_at = booked_at = брондалған уақыт."""
    last = conn.execute("SELECT MAX(seq) FROM tickets WHERE day=? AND service_id=?",
                        (day, service["id"])).fetchone()[0]
    seq = ql.next_sequence(last)
    token = secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO tickets (number, seq, day, service_id, user_id, full_name, student_id, "
        "group_name, priority, token, created_at, booked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ql.format_ticket_number(service["code"], seq), seq, day, service["id"], user["id"],
         user["full_name"], user["student_id"], user["group_name"], 1 if (priority or booked) else 0,
         token, ts(created), ts(created) if booked else None))
    return token


def create_booking(conn, user, service_id, slot: datetime, now: datetime) -> sqlite3.Row:
    """Алдын ала брондау: кезек шегінен тыс; уақыты келгенде талон кезектің басына шығады."""
    service = _ticket_service(conn, user, service_id, now, check_hours=False)
    ql.validate_booking(slot, now, get_schedule(conn), get_overrides(conn))
    day = slot.strftime("%Y-%m-%d")
    conn.execute("BEGIN IMMEDIATE")
    try:
        _check_ticket_limits(conn, day, user["id"], service["id"])
        if conn.execute("SELECT 1 FROM tickets WHERE service_id=? AND booked_at=? "
                        "AND status IN ('waiting','called')", (service["id"], ts(slot))).fetchone():
            raise ql.QueueError("err_slot_taken")
        token = _insert_ticket(conn, user, service, day, slot, priority=True, booked=True)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    log(conn, user["id"], "booking", f"{service['code']} {ts(slot)}", now)
    return get_ticket_by_token(conn, token)


TICKET_SELECT = ("SELECT t.*, s.code AS service_code, s.name_kk, s.name_ru, "
                 "COALESCE(NULLIF(s.name_en, ''), s.name_ru) AS name_en "
                 "FROM tickets t JOIN services s ON s.id = t.service_id ")


def get_ticket_by_token(conn, token: str) -> sqlite3.Row | None:
    if not token or len(token) > 64:
        return None
    return conn.execute(TICKET_SELECT + "WHERE t.token=?", (token,)).fetchone()


def get_ticket(conn, ticket_id: int) -> sqlite3.Row | None:
    return conn.execute(TICKET_SELECT + "WHERE t.id=?", (ticket_id,)).fetchone()


def user_tickets(conn, user_id: int, limit: int = 30) -> list[sqlite3.Row]:
    return conn.execute(TICKET_SELECT + "WHERE t.user_id=? ORDER BY t.id DESC LIMIT ?",
                        (user_id, limit)).fetchall()


def tickets_for_day(conn, now: datetime) -> list[sqlite3.Row]:
    return conn.execute(TICKET_SELECT + "WHERE t.day=? ORDER BY t.id DESC",
                        (now.strftime("%Y-%m-%d"),)).fetchall()


def tickets_between(conn, start: str, end: str) -> list[dict]:
    """[start, end] күндер аралығындағы барлық талон (есеп пен CSV үшін)."""
    rows = conn.execute(TICKET_SELECT + "WHERE t.day BETWEEN ? AND ? ORDER BY t.day, t.id",
                        (start, end)).fetchall()
    return [dict(r) for r in rows]


def backup_bytes(conn) -> bytes:
    """Дерекқордың толық көшірмесі (SQLite backup API) — файл ретінде жүктеуге."""
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        target = sqlite3.connect(path)
        with target:
            conn.backup(target)
        target.close()
        return Path(path).read_bytes()
    finally:
        os.remove(path)


def people_ahead(conn, ticket, now: datetime | None = None) -> int:
    """Осы талонның алдында тұрған күтудегі адамдар саны (уақыты келмеген брондаулар есепке алынбайды)."""
    stamp = ts(now or datetime.now())
    if ticket["status"] != ql.WAITING or (ticket["booked_at"] and ticket["booked_at"] > stamp):
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE day=? AND service_id=? AND status='waiting' "
        f"AND {DUE} AND (priority > ? OR (priority = ? AND (created_at < ? OR "
        "(created_at = ? AND id < ?))))",
        (ticket["day"], ticket["service_id"], stamp, ticket["priority"], ticket["priority"],
         ticket["created_at"], ticket["created_at"], ticket["id"])).fetchone()[0]


def waiting_count(conn, service_id: int, day: str, now: datetime | None = None) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM tickets WHERE day=? AND service_id=? AND status='waiting' AND {DUE}",
        (day, service_id, ts(now or datetime.now()))).fetchone()[0]


def recent_durations(conn, service_id: int, limit: int = 20) -> list[float]:
    rows = conn.execute(
        "SELECT called_at, finished_at FROM tickets WHERE service_id=? AND status='done' "
        "AND called_at IS NOT NULL AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT ?", (service_id, limit)).fetchall()
    out = []
    for r in rows:
        delta = (parse_ts(r["finished_at"]) - parse_ts(r["called_at"])).total_seconds() / 60
        out.append(round(delta, 2))
    return out


def active_windows(conn, service_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users u JOIN user_services us ON us.user_id=u.id "
        "WHERE us.service_id=? AND u.on_duty=1 AND u.on_break=0 AND u.is_active=1", (service_id,)).fetchone()[0]


def estimate_for_service(conn, service, ahead: int) -> int:
    avg = ql.average_duration(recent_durations(conn, service["id"]), service["avg_minutes"])
    return ql.estimate_wait_minutes(ahead, avg, active_windows(conn, service["id"]))


def services_overview(conn, now: datetime) -> list[dict]:
    """Әр қызмет бойынша кезек ұзындығы мен болжам."""
    day = now.strftime("%Y-%m-%d")
    result = []
    for s in list_services(conn):
        n = waiting_count(conn, s["id"], day, now)
        result.append({"id": s["id"], "code": s["code"], "name_kk": s["name_kk"], "name_en": s["name_en"],
                       "name_ru": s["name_ru"], "waiting": n,
                       "minutes": f"{float(s['avg_minutes']):g}",
                       "estimate": estimate_for_service(conn, s, n),
                       "windows": active_windows(conn, s["id"])})
    return result


def cancel_ticket(conn, ticket_id: int, user_id: int, now: datetime) -> None:
    """Студент өз талонынан бас тартады."""
    t = get_ticket(conn, ticket_id)
    if t is None:
        raise ql.QueueError("err_not_found")
    if t["user_id"] != user_id:
        raise ql.QueueError("err_forbidden")
    ql.ensure_transition(t["status"], ql.CANCELLED)
    conn.execute("UPDATE tickets SET status='cancelled', finished_at=? WHERE id=? "
                 "AND status='waiting'", (ts(now), t["id"]))


# ---------------------------------------------------------------------------
# Деканат қызметкерінің әрекеттері
# ---------------------------------------------------------------------------
def waiting_for_services(conn, service_ids: set[int], now: datetime) -> list[sqlite3.Row]:
    """Деканат панелі үшін: қызметкердің қызметтері бойынша күтудегі талондар."""
    if not service_ids:
        return []
    ids = sorted(int(i) for i in service_ids)
    placeholders = ",".join("?" for _ in ids)  # тек «?» белгілері, мәндер параметр ретінде
    return conn.execute(
        "SELECT t.number, t.full_name, t.group_name, t.priority, t.created_at, s.code "
        "FROM tickets t JOIN services s ON s.id=t.service_id "
        f"WHERE t.day=? AND t.status='waiting' AND {DUE_T} AND t.service_id IN ({placeholders}) "
        "ORDER BY t.priority DESC, t.created_at, t.id",
        (now.strftime("%Y-%m-%d"), ts(now), *ids)).fetchall()


def current_ticket(conn, operator_id: int) -> sqlite3.Row | None:
    return conn.execute(TICKET_SELECT + "WHERE t.operator_id=? AND t.status='called' "
                        "ORDER BY t.called_at DESC LIMIT 1", (operator_id,)).fetchone()


def _require_window_operator(conn, operator_id: int) -> sqlite3.Row:
    """Шақыра алатын қызметкер: рөлі дұрыс, үзілісте емес, терезесі бар."""
    op = get_user(conn, operator_id)
    if op is None or op["role"] not in ql.STAFF_ROLES:
        raise ql.QueueError("err_forbidden")
    if op["on_break"]:
        raise ql.QueueError("err_on_break")
    if not op["window_no"]:
        raise ql.QueueError("err_window")
    return op


def call_next(conn, operator_id: int, now: datetime) -> sqlite3.Row | None:
    """Келесі студентті шақырады. Кезек бос болса None қайтарады."""
    op = _require_window_operator(conn, operator_id)
    conn.execute("BEGIN IMMEDIATE")  # екі қызметкер бір талонды алмауы үшін
    try:
        if conn.execute("SELECT 1 FROM tickets WHERE operator_id=? AND status='called'",
                        (operator_id,)).fetchone():
            raise ql.QueueError("err_finish_current")
        day = now.strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT id, service_id, created_at, priority FROM tickets "
            f"WHERE day=? AND status='waiting' AND {DUE}", (day, ts(now))).fetchall()
        nxt = ql.pick_next([dict(r) for r in rows], user_service_ids(conn, operator_id))
        if nxt is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE tickets SET status='called', operator_id=?, window_no=?, called_at=? "
            "WHERE id=? AND status='waiting'",
            (operator_id, op["window_no"], ts(now), nxt["id"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return current_ticket(conn, operator_id)


def finish_ticket(conn, operator_id: int, ticket_id: int, new_status: str,
                  now: datetime) -> None:
    """Қызметті аяқтау: done | no_show | waiting (кезекке қайтару)."""
    t = get_ticket(conn, ticket_id)
    if t is None:
        raise ql.QueueError("err_not_found")
    if t["operator_id"] != operator_id:
        raise ql.QueueError("err_forbidden")
    ql.ensure_transition(t["status"], new_status)
    if new_status == ql.WAITING:
        conn.execute("UPDATE tickets SET status='waiting', operator_id=NULL, window_no=NULL, "
                     "called_at=NULL WHERE id=?", (ticket_id,))
    else:
        conn.execute("UPDATE tickets SET status=?, finished_at=? WHERE id=?",
                     (new_status, ts(now), ticket_id))


def recall_ticket(conn, operator_id: int, ticket_id: int) -> None:
    t = get_ticket(conn, ticket_id)
    if t is None or t["operator_id"] != operator_id or t["status"] != ql.CALLED:
        raise ql.QueueError("err_forbidden")
    conn.execute("UPDATE tickets SET recall_count = recall_count + 1 WHERE id=?",
                 (ticket_id,))


# ---------------- Әкімші: талондарды түзету ----------------
def admin_set_ticket_status(conn, admin_id: int, ticket_id: int, status: str,
                            now: datetime) -> None:
    """Әкімші қате қойылған күйді кез келген күйге түзете алады (журналға жазылады)."""
    _require_manager(conn, admin_id)
    t = get_ticket(conn, ticket_id)
    if t is None:
        raise ql.QueueError("err_not_found")
    if status not in ALL_STATUSES:
        raise ql.QueueError("err_bad_transition")
    if status == t["status"]:
        return
    if status == ql.WAITING:
        conn.execute("UPDATE tickets SET status='waiting', operator_id=NULL, window_no=NULL, "
                     "called_at=NULL, finished_at=NULL WHERE id=?", (ticket_id,))
    elif status == ql.CALLED:
        raise ql.QueueError("err_admin_call")  # шақыруды тек деканат панелі жасайды
    else:
        conn.execute("UPDATE tickets SET status=?, finished_at=COALESCE(finished_at, ?) "
                     "WHERE id=?", (status, ts(now), ticket_id))
    log(conn, admin_id, "ticket_status", f"{t['number']} ({t['day']}): {t['status']} -> {status}", now)


def admin_delete_ticket(conn, admin_id: int, ticket_id: int, now: datetime) -> None:
    _require_manager(conn, admin_id)
    t = get_ticket(conn, ticket_id)
    if t is None:
        raise ql.QueueError("err_not_found")
    conn.execute("DELETE FROM tickets WHERE id=?", (ticket_id,))
    log(conn, admin_id, "delete_ticket", f"{t['number']} ({t['day']})", now)


ALL_STATUSES = (ql.WAITING, ql.CALLED, ql.DONE, ql.NO_SHOW, ql.CANCELLED)


# ---------------------------------------------------------------------------
# Табло және статистика
# ---------------------------------------------------------------------------
def board_data(conn, now: datetime) -> dict:
    day = now.strftime("%Y-%m-%d")
    called = conn.execute(
        "SELECT number, window_no, recall_count, called_at FROM tickets "
        "WHERE day=? AND status='called' ORDER BY called_at DESC, id DESC", (day,)).fetchall()
    waiting = conn.execute(
        "SELECT t.number, s.name_kk, s.name_ru, COALESCE(NULLIF(s.name_en, ''), s.name_ru) AS name_en "
        "FROM tickets t JOIN services s ON s.id = t.service_id "
        f"WHERE t.day=? AND t.status='waiting' AND {DUE_T} "
        "ORDER BY t.priority DESC, t.created_at, t.id", (day, ts(now))).fetchall()
    windows = conn.execute(
        "SELECT window_no, on_break FROM users WHERE on_duty=1 AND is_active=1 "
        "AND window_no IS NOT NULL ORDER BY window_no").fetchall()
    return {"called": [dict(r) for r in called],
            "waiting": [r["number"] for r in waiting],
            "queue": [{"pos": i, "number": r["number"], "name_kk": r["name_kk"], "name_ru": r["name_ru"],
                       "name_en": r["name_en"]}
                      for i, r in enumerate(waiting, 1)],
            "windows": [{"window_no": w["window_no"], "on_break": bool(w["on_break"])} for w in windows]}


def stats_today(conn, now: datetime) -> dict:
    day = now.strftime("%Y-%m-%d")
    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM tickets WHERE day=? GROUP BY status", (day,))}
    rows = conn.execute(
        "SELECT created_at, called_at, finished_at FROM tickets WHERE day=? AND status='done' "
        "AND called_at IS NOT NULL", (day,)).fetchall()
    waits = [(parse_ts(r["called_at"]) - parse_ts(r["created_at"])).total_seconds() / 60
             for r in rows]
    serv = [(parse_ts(r["finished_at"]) - parse_ts(r["called_at"])).total_seconds() / 60
            for r in rows]
    return {
        "total": sum(counts.values()),
        "waiting": counts.get("waiting", 0),
        "called": counts.get("called", 0),
        "done": counts.get("done", 0),
        "no_show": counts.get("no_show", 0),
        "cancelled": counts.get("cancelled", 0),
        "avg_wait": round(sum(waits) / len(waits), 1) if waits else 0,
        "avg_service": round(sum(serv) / len(serv), 1) if serv else 0,
    }
