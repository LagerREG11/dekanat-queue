"""
Бизнес-логика модулі (дерекқорға және Flask-қа тәуелсіз).

Мұнда тек «таза» функциялар бар: олар деректерді қабылдап, нәтиже қайтарады.
Сондықтан оларды тесттермен оңай тексеруге болады (tests/test_service.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from math import ceil

# ---------------------------------------------------------------------------
# Рөлдер
# ---------------------------------------------------------------------------
STUDENT = "student"   # талон алады, өз талондарын көреді
DEKANAT = "dekanat"   # деканат қызметкері (әдіскер): студенттерді шақырады
DEPUTY = "deputy"     # декан орынбасары: декан жұмысын атқарады (әкімші аккаунттарынан басқасы)
ADMIN = "admin"       # декан / әкімші: толық құқық
ROLES = (STUDENT, DEKANAT, DEPUTY, ADMIN)
MANAGER_ROLES = (DEPUTY, ADMIN)          # әкімші панеліне кіре алатындар
STAFF_ROLES = (DEKANAT, DEPUTY, ADMIN)   # студенттерді қабылдай алатындар


def can_manage_user(actor_role: str, target_role: str, new_role: str | None = None) -> bool:
    """Аккаунтты өзгертуге құқық бар ма?

    Декан (admin) — бәрін өзгерте алады. Декан орынбасары — декан аккаунттарын
    өзгерте алмайды және ешкімге декан рөлін бере алмайды. Басқа рөлдер — ешкімді.
    """
    if actor_role == ADMIN:
        return True
    if actor_role == DEPUTY:
        return target_role != ADMIN and new_role != ADMIN
    return False

# ---------------------------------------------------------------------------
# Талон күйлері және рұқсат етілген өтулер (state machine)
# ---------------------------------------------------------------------------
WAITING = "waiting"      # кезекте күтуде
CALLED = "called"        # операторға шақырылды
DONE = "done"            # қызмет көрсетілді
NO_SHOW = "no_show"      # келмеді
CANCELLED = "cancelled"  # студент өзі бас тартты

ACTIVE_STATUSES = (WAITING, CALLED)
FINAL_STATUSES = (DONE, NO_SHOW, CANCELLED)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    WAITING: {CALLED, CANCELLED},
    CALLED: {DONE, NO_SHOW, WAITING},  # WAITING — кезекке қайтару
    DONE: set(),
    NO_SHOW: set(),
    CANCELLED: set(),
}


class QueueError(Exception):
    """Бизнес-ереже бұзылғанда шығарылатын қате. code — аударма кілті."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def can_transition(current: str, new: str) -> bool:
    """Талонды current күйінен new күйіне ауыстыруға бола ма?"""
    if current not in ALLOWED_TRANSITIONS:
        return False
    return new in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: str, new: str) -> None:
    if not can_transition(current, new):
        raise QueueError("err_bad_transition")


# ---------------------------------------------------------------------------
# Талон нөмірі
# ---------------------------------------------------------------------------
def format_ticket_number(service_code: str, seq: int) -> str:
    """'A', 7 -> 'A-007'. Нөмір 1..999 аралығында болуы керек."""
    if not service_code or not service_code.isalpha() or len(service_code) > 2:
        raise QueueError("err_bad_service_code")
    if not isinstance(seq, int) or seq < 1 or seq > 999:
        raise QueueError("err_daily_limit")
    return f"{service_code.upper()}-{seq:03d}"


def next_sequence(last_seq: int | None, daily_limit: int = 999) -> int:
    """Бүгінгі соңғы нөмірден кейінгі нөмірді қайтарады (күн сайын 1-ден басталады)."""
    nxt = 1 if not last_seq else last_seq + 1
    if nxt > daily_limit:
        raise QueueError("err_daily_limit")
    return nxt


# ---------------------------------------------------------------------------
# Студент деректерін тексеру
# ---------------------------------------------------------------------------
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі\-\s']{3,80}$")
STUDENT_ID_RE = re.compile(r"^\d{6,12}$")          # сынақ кітапшасы / ID нөмірі
GROUP_RE = re.compile(r"^[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі0-9\-]{2,20}$")


@dataclass
class TicketRequest:
    full_name: str
    student_id: str
    group_name: str
    service_id: int


def validate_ticket_request(full_name: str, student_id: str, group_name: str,
                            service_id) -> tuple[TicketRequest | None, list[str]]:
    """Форма деректерін тазалап, тексереді. (нәтиже, қате_кілттері) қайтарады."""
    errors: list[str] = []
    full_name = " ".join((full_name or "").split())
    student_id = (student_id or "").strip()
    group_name = (group_name or "").strip().upper()

    if not NAME_RE.match(full_name):
        errors.append("err_name")
    if not STUDENT_ID_RE.match(student_id):
        errors.append("err_student_id")
    if group_name and not GROUP_RE.match(group_name):
        errors.append("err_group")
    try:
        sid = int(service_id)
        if sid <= 0:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("err_service")
        sid = 0

    if errors:
        return None, errors
    return TicketRequest(full_name, student_id, group_name, sid), []


# ---------------------------------------------------------------------------
# Тіркелу деректерін тексеру
# ---------------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,30}$")


def validate_password(password: str, password2: str | None = None) -> list[str]:
    """Құпиясөз: кемінде 8 таңба, әріп пен цифр болуы керек, 128 таңбадан аспайды."""
    errors = []
    password = password or ""
    if (len(password) < 8 or len(password) > 128 or not any(c.isdigit() for c in password)
            or not any(c.isalpha() for c in password)):
        errors.append("err_password_weak")
    if password2 is not None and password != password2:
        errors.append("err_password_mismatch")
    return errors


@dataclass
class Registration:
    role: str
    username: str
    full_name: str
    student_id: str | None
    group_name: str
    password: str


def validate_registration(kind: str, full_name: str, password: str, password2: str,
                          student_id: str = "", group_name: str = "",
                          username: str = "") -> tuple[Registration | None, list[str]]:
    """Тіркелу формасын тексереді.

    kind='student' — логин ретінде студенттік ID қолданылады.
    kind='dekanat' | 'deputy' | 'admin' — қызметкер өз логинін таңдайды. Мұндай аккаунт
    растауды күтеді (is_active=0): оны db.register() белсенді емес етіп жасайды, ал
    рұқсатты can_manage_user() бойынша декан немесе (декандықтан басқасын) орынбасар береді.
    """
    errors: list[str] = []
    if kind not in ROLES:
        return None, ["err_role"]
    full_name = " ".join((full_name or "").split())
    if not NAME_RE.match(full_name):
        errors.append("err_name")

    if kind == STUDENT:
        student_id = (student_id or "").strip()
        group_name = (group_name or "").strip().upper()
        if not STUDENT_ID_RE.match(student_id):
            errors.append("err_student_id")
        if not group_name or not GROUP_RE.match(group_name):
            errors.append("err_group")
        username = student_id
    else:
        username = (username or "").strip().lower()
        student_id, group_name = None, ""
        if not USERNAME_RE.match(username):
            errors.append("err_username")

    errors += validate_password(password, password2)
    if errors:
        return None, errors
    return Registration(kind, username, full_name, student_id, group_name, password), []


# ---------------------------------------------------------------------------
# Күту уақытының болжамы
# ---------------------------------------------------------------------------
def average_duration(recent_minutes: list[float], default_minutes: float,
                     min_samples: int = 3) -> float:
    """Соңғы қызмет көрсету ұзақтықтарының орташасы.

    Деректер аз болса (min_samples-тен кем) — қызметтің әдепкі уақыты алынады.
    Шектен тыс мәндер (0 немесе одан кем, 120 минуттан көп) есепке алынбайды.
    Нақты орташа мән 80%, әдепкі мән 20% салмақпен біріктіріледі —
    бұл бір-екі өте ұзақ қабылдаудың болжамды күрт бұзуына жол бермейді.
    """
    clean = [m for m in recent_minutes if 0 < m <= 120]
    if len(clean) < min_samples:
        return float(default_minutes)
    avg = sum(clean) / len(clean)
    return round(0.8 * avg + 0.2 * default_minutes, 2)


def estimate_wait_minutes(people_ahead: int, avg_minutes: float,
                          active_windows: int) -> int:
    """Алда тұрған адам саны бойынша күту уақытын болжау (минутпен).

    Формула: ceil(people_ahead / windows) * avg_minutes
    Белсенді терезе жоқ болса — бір терезе жұмыс істейді деп есептейміз.
    """
    if people_ahead < 0 or avg_minutes <= 0:
        raise QueueError("err_negative")
    if people_ahead == 0:
        return 0
    windows = max(1, int(active_windows))
    rounds = ceil(people_ahead / windows)
    return int(ceil(rounds * avg_minutes))


# ---------------------------------------------------------------------------
# Жұмыс уақыты
# ---------------------------------------------------------------------------
MAX_BREAKS = 5            # бір күндегі қосымша үзілістердің ең көп саны
MAX_BREAK_MINUTES = 60    # бір қысқа үзілістің ең ұзақ уақыты


@dataclass(frozen=True)
class Schedule:
    """Деканаттың жұмыс кестесі: жұмыс уақыты, түскі үзіліс, қысқа үзілістер."""
    open_at: time = time(9, 0)
    close_at: time = time(18, 0)
    lunch_from: time | None = time(13, 0)
    lunch_to: time | None = time(14, 0)
    workdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # 0 = дүйсенбі ... 6 = жексенбі
    breaks: tuple[tuple[time, time], ...] = ()   # мысалы ((11:00, 11:15), (16:00, 16:15))


DEFAULT_SCHEDULE = Schedule(breaks=((time(11, 0), time(11, 15)), (time(16, 0), time(16, 15))))


def current_pause(now: datetime, schedule: Schedule = DEFAULT_SCHEDULE) -> str | None:
    """Қазір үзіліс болса — оның түрі ('lunch' не 'break'), әйтпесе None."""
    t = now.time()
    if schedule.lunch_from and schedule.lunch_from <= t < schedule.lunch_to:
        return "lunch"
    if any(start <= t < end for start, end in schedule.breaks):
        return "break"
    return None


def is_open(now: datetime, schedule: Schedule = DEFAULT_SCHEDULE) -> bool:
    """Деканат қазір қабылдау жүргізе ме? (жұмыс күні, жұмыс уақыты, үзіліс емес)"""
    if now.weekday() not in schedule.workdays:
        return False
    t = now.time()
    if t < schedule.open_at or t >= schedule.close_at:
        return False
    return current_pause(now, schedule) is None


def parse_hhmm(value: str) -> time:
    """'09:00' -> time(9, 0). Қате болса QueueError('err_time')."""
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", value or "")
    if not m:
        raise QueueError("err_time")
    return time(int(m.group(1)), int(m.group(2)))


def parse_breaks(text: str) -> tuple[tuple[time, time], ...]:
    """'11:00-11:15, 16:00-16:15' -> ((11:00, 11:15), (16:00, 16:15)). Бос мәтін -> ()."""
    items = [p for p in re.split(r"[,;\n]+", text or "") if p.strip()]
    if len(items) > MAX_BREAKS:
        raise QueueError("err_breaks_many")
    result = []
    for item in items:
        parts = re.split(r"\s*[-–—]\s*", item.strip())
        if len(parts) != 2:
            raise QueueError("err_time")
        result.append((parse_hhmm(parts[0]), parse_hhmm(parts[1])))
    return tuple(sorted(result))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def build_schedule(open_at: str, close_at: str, lunch_from: str, lunch_to: str,
                   breaks: str, workdays) -> Schedule:
    """Форма мәндерінен кестені құрып, ережелерін тексереді."""
    start, end = parse_hhmm(open_at), parse_hhmm(close_at)
    if start >= end:
        raise QueueError("err_hours_order")
    lunch = (None, None)
    if (lunch_from or "").strip() or (lunch_to or "").strip():
        lunch = (parse_hhmm(lunch_from), parse_hhmm(lunch_to))
        _check_interval(lunch, start, end, "err_lunch")
    pauses = parse_breaks(breaks)
    for interval in pauses:
        _check_interval(interval, start, end, "err_break")
        if _minutes(interval[1]) - _minutes(interval[0]) > MAX_BREAK_MINUTES:
            raise QueueError("err_break_long")
    _check_no_overlap(list(pauses) + ([lunch] if lunch[0] else []))
    days = tuple(sorted({int(d) for d in workdays if str(d).isdigit() and 0 <= int(d) <= 6}))
    if not days:
        raise QueueError("err_workdays")
    return Schedule(start, end, lunch[0], lunch[1], days, pauses)


def _check_interval(interval, start: time, end: time, code: str) -> None:
    a, b = interval
    if not (start <= a < b <= end):
        raise QueueError(code)


def _check_no_overlap(intervals) -> None:
    ordered = sorted(intervals)
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:]):
        if next_start < prev_end:
            raise QueueError("err_break_overlap")


def schedule_to_dict(s: Schedule) -> dict:
    """Кестені JSON-ға сақтау үшін сөздікке айналдырады."""
    fmt = lambda t: t.strftime("%H:%M") if t else ""
    return {"open_at": fmt(s.open_at), "close_at": fmt(s.close_at),
            "lunch_from": fmt(s.lunch_from), "lunch_to": fmt(s.lunch_to),
            "workdays": list(s.workdays),
            "breaks": ", ".join(f"{fmt(a)}-{fmt(b)}" for a, b in s.breaks)}


def schedule_from_dict(d: dict) -> Schedule:
    return build_schedule(d["open_at"], d["close_at"], d.get("lunch_from", ""),
                          d.get("lunch_to", ""), d.get("breaks", ""), d["workdays"])


def minutes_until_close(now: datetime, schedule: Schedule = DEFAULT_SCHEDULE) -> int:
    close_dt = datetime.combine(now.date(), schedule.close_at)
    return max(0, int((close_dt - now).total_seconds() // 60))


def can_be_served_today(now: datetime, wait_minutes: int,
                        schedule: Schedule = DEFAULT_SCHEDULE) -> bool:
    """Болжамды күту уақыты жұмыс күнінің соңына дейін сыя ма?"""
    return wait_minutes <= minutes_until_close(now, schedule)


# ---------------------------------------------------------------------------
# Кезектен келесі талонды таңдау
# ---------------------------------------------------------------------------
def pick_next(waiting: list[dict], service_ids: set[int] | None = None) -> dict | None:
    """Келесі талонды таңдайды: алдымен басымдығы бар, сосын ең ерте алынған (FIFO).

    waiting — {'id', 'service_id', 'created_at', 'priority'} сөздіктер тізімі.
    priority=1 (мысалы, мүмкіндігі шектеулі студент) — алдымен шақырылады.
    service_ids берілсе, тек сол қызметтер қаралады.
    """
    pool = [t for t in waiting if service_ids is None or t["service_id"] in service_ids]
    if not pool:
        return None
    return sorted(pool, key=lambda t: (-int(t.get("priority", 0)), t["created_at"], t["id"]))[0]
