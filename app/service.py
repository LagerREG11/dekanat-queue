"""
Бизнес-логика модулі (дерекқорға және Flask-қа тәуелсіз).

Мұнда тек «таза» функциялар бар: олар деректерді қабылдап, нәтиже қайтарады.
Сондықтан оларды тесттермен оңай тексеруге болады (tests/test_service.py).
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from math import ceil

# ---------------------------------------------------------------------------
# Рөлдер
# ---------------------------------------------------------------------------
STUDENT = "student"   # талон алады, өз талондарын көреді
DEKANAT = "dekanat"   # декан: студенттерді шақырады, аккаунттарды басқарады (администратордан басқа)
DEPUTY = "deputy"     # декан орынбасары: студенттер мен орынбасарлар аккаунттарын басқарады
ADMIN = "admin"       # администратор: толық құқық
# Иерархия бойынша (жоғарыдан төмен) — кіру/тіркелу қойындылары да осы ретпен шығады.
ROLES = (ADMIN, DEKANAT, DEPUTY, STUDENT)
ROLE_RANK = {ADMIN: 4, DEKANAT: 3, DEPUTY: 2, STUDENT: 1}
MANAGER_ROLES = (ADMIN, DEKANAT, DEPUTY)   # әкімші панеліне кіре алатындар
STAFF_ROLES = (ADMIN, DEKANAT, DEPUTY)     # студенттерді қабылдай алатындар


def can_manage_user(actor_role: str, target_role: str, new_role: str | None = None) -> bool:
    """Аккаунтты өзгертуге құқық бар ма? Иерархия: администратор > декан > орынбасар > студент.

    Администратор — бәрін өзгерте алады. Декан мен орынбасар — өзінен жоғары тұрған
    аккаунттарды өзгерте алмайды және өзінен жоғары рөлді бере алмайды. Студент — ешкімді.
    """
    if actor_role == ADMIN:
        return True
    if actor_role not in (DEKANAT, DEPUTY):
        return False
    rank = ROLE_RANK[actor_role]
    if ROLE_RANK.get(target_role, 0) > rank:
        return False
    return new_role is None or ROLE_RANK.get(new_role, 99) <= rank

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
STUDENT_ID_RE = re.compile(r"^\d{6,12}$")          # ескі студенттік ID (бұрынғы аккаунттар)
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
# ЖСН (ИИН) тексеру
# ---------------------------------------------------------------------------
IIN_WEIGHTS_1 = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
IIN_WEIGHTS_2 = (3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2)
IIN_CENTURY = {"1": 1800, "2": 1800, "3": 1900, "4": 1900, "5": 2000, "6": 2000}


def iin_control_digit(first11: str) -> int | None:
    """ЖСН-нің 12-ші (бақылау) цифры. Есептеу мүмкін болмаса (екі рет 10 шықса) — None."""
    digits = [int(c) for c in first11]
    rest = sum(d * w for d, w in zip(digits, IIN_WEIGHTS_1)) % 11
    if rest == 10:
        rest = sum(d * w for d, w in zip(digits, IIN_WEIGHTS_2)) % 11
    return None if rest == 10 else rest


def is_valid_iin(iin: str) -> bool:
    """ЖСН: 12 цифр, алғашқы 6-уы — туған күні (ЖЖААКК), 7-сі — ғасыр мен жыныс,
    соңғысы — бақылау цифры (ресми алгоритм бойынша)."""
    iin = (iin or "").strip()
    if not re.fullmatch(r"\d{12}", iin) or iin[6] not in IIN_CENTURY:
        return False
    try:
        date(IIN_CENTURY[iin[6]] + int(iin[:2]), int(iin[2:4]), int(iin[4:6]))
    except ValueError:
        return False
    return iin_control_digit(iin[:11]) == int(iin[11])


# ---------------------------------------------------------------------------
# Тіркелу деректерін тексеру
# ---------------------------------------------------------------------------
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,30}$")
PASSWORD_MIN, PASSWORD_MAX = 8, 16
WEAK, MEDIUM, STRONG = "weak", "medium", "strong"


def password_strength(password: str) -> str:
    """Құпиясөздің беріктігі.

    strong — тыныс белгісі (не басқа арнайы таңба), әріп және цифр аралас;
    medium — кіші әріп, бас әріп және цифр аралас;
    weak   — қалғандары (мысалы, «aigerim2005»: тек кіші әріп пен туған жыл),
             сондай-ақ 8 таңбадан қысқа құпиясөз.
    """
    password = password or ""
    if len(password) < PASSWORD_MIN:
        return WEAK
    has_digit = any(c.isdigit() for c in password)
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_symbol = any(not c.isalnum() and not c.isspace() for c in password)
    if has_symbol and (has_lower or has_upper) and has_digit:
        return STRONG
    if has_lower and has_upper and has_digit:
        return MEDIUM
    return WEAK


def validate_password(password: str, password2: str | None = None) -> list[str]:
    """Құпиясөз: 8–16 таңба, бос орынсыз, кемінде «орташа» беріктікте болуы керек."""
    errors = []
    password = password or ""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX or any(c.isspace() for c in password):
        errors.append("err_password_length")
    elif password_strength(password) == WEAK:
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


def _registration_login(kind: str, student_id: str, group_name: str,
                        username: str) -> tuple[str, str | None, str, list[str]]:
    """Логинді анықтайды. Барлығы өз логинін таңдайды (студент қаласа, ЖСН-ін жаза алады).

    Студенттің логині student_id өрісінде де сақталады (талонда көрсетіледі). Тобы міндетті
    емес — студент оны кейін профильде толтырады; жазылса, пішімі тексеріледі.
    """
    errors: list[str] = []
    if kind == STUDENT:
        login = (username or student_id or "").strip().lower()
        group_name = validate_group(group_name, errors)
        if not USERNAME_RE.match(login):
            errors.append("err_username")
        return login, login, group_name, errors
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        errors.append("err_username")
    return username, None, "", errors


def validate_registration(kind: str, full_name: str, password: str, password2: str,
                          student_id: str = "", group_name: str = "",
                          username: str = "") -> tuple[Registration | None, list[str]]:
    """Тіркелу формасын тексереді.

    Тіркелуде міндетті: аты-жөні, логин және құпиясөз. Сайтта өзі тек студент тіркеледі;
    қызметкер аккаунтын администратор ашады (сол функция арқылы тексеріледі).
    """
    errors: list[str] = []
    if kind not in ROLES:
        return None, ["err_role"]
    full_name = " ".join((full_name or "").split())
    if not NAME_RE.match(full_name):
        errors.append("err_name")

    username, student_id, group_name, login_errors = _registration_login(
        kind, student_id, group_name, username)
    errors += login_errors
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
    return ceil(rounds * avg_minutes)


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


DEFAULT_SCHEDULE = Schedule()  # қысқа үзілістер жоқ, тек түскі үзіліс


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
    for (_, prev_end), (next_start, _) in pairwise(ordered):
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
# Талон алу уақыты, мерекелер, ерекше күндер, айлық күнтізбе
# ---------------------------------------------------------------------------
BOOKING_LEAD_MINUTES = 15  # талон жұмыс басталардан 15 минут бұрын беріледі (09:00 -> 08:45)

# Қазақстанның тұрақты күнге белгіленген мерекелері (ай, күн) -> (қазақша, орысша).
# Құрбан айт сияқты жылжымалы мерекелерді декан «Ерекше күн» ретінде қосады.
HOLIDAYS: dict[tuple[int, int], tuple[str, str]] = {
    (1, 1): ("Жаңа жыл", "Новый год"),
    (1, 2): ("Жаңа жыл", "Новый год"),
    (1, 7): ("Рождество", "Рождество"),
    (3, 8): ("Халықаралық әйелдер күні", "Международный женский день"),
    (3, 21): ("Наурыз мейрамы", "Наурыз мейрамы"),
    (3, 22): ("Наурыз мейрамы", "Наурыз мейрамы"),
    (3, 23): ("Наурыз мейрамы", "Наурыз мейрамы"),
    (5, 1): ("Қазақстан халқының бірлігі мерекесі", "Праздник единства народа Казахстана"),
    (5, 7): ("Отан қорғаушы күні", "День защитника Отечества"),
    (5, 9): ("Жеңіс күні", "День Победы"),
    (7, 6): ("Астана күні", "День столицы"),
    (8, 30): ("Конституция күні", "День Конституции"),
    (10, 25): ("Республика күні", "День Республики"),
    (12, 16): ("Тәуелсіздік күні", "День Независимости"),
}

HOLIDAY, SHORT = "holiday", "short"   # ерекше күн түрлері
DAY_KINDS = (HOLIDAY, SHORT)
NOTE_MAX = 200


@dataclass(frozen=True)
class DayOverride:
    """Декан белгілеген ерекше күн: демалыс/мереке не қысқартылған жұмыс күні."""
    day: date
    kind: str                    # 'holiday' | 'short'
    open_at: time | None = None  # тек 'short' үшін
    close_at: time | None = None
    note: str = ""               # мысалы: «Декан жиналыста, 13:00-ден кейін қабылдау жоқ»


@dataclass(frozen=True)
class DayPlan:
    """Белгілі бір күннің жоспары: түрі, сол күнгі кесте (жұмыс күні болса) және ескерту."""
    kind: str                       # 'work' | 'short' | 'weekend' | 'holiday'
    schedule: Schedule | None
    note: str = ""
    holiday: tuple[str, str] | None = None


def build_override(day: str, kind: str, open_at: str = "", close_at: str = "",
                   note: str = "") -> DayOverride:
    """Форма мәндерінен ерекше күнді құрып, тексереді."""
    try:
        d = date.fromisoformat((day or "").strip())
    except ValueError:
        raise QueueError("err_date")
    if kind not in DAY_KINDS:
        raise QueueError("err_day_kind")
    note = " ".join((note or "").split())
    if len(note) > NOTE_MAX:
        raise QueueError("err_note_long")
    if kind == HOLIDAY:
        return DayOverride(d, kind, None, None, note)
    start, end = parse_hhmm(open_at), parse_hhmm(close_at)
    if start >= end:
        raise QueueError("err_hours_order")
    return DayOverride(d, kind, start, end, note)


def day_plan(d: date, schedule: Schedule = DEFAULT_SCHEDULE,
             overrides: dict[date, DayOverride] | None = None) -> DayPlan:
    """Күннің жоспары. Басымдық: декан белгілеген ерекше күн > мереке > демалыс > кесте."""
    override = (overrides or {}).get(d)
    holiday = HOLIDAYS.get((d.month, d.day))
    if override is not None:
        if override.kind == HOLIDAY:
            return DayPlan(HOLIDAY, None, override.note, holiday)
        short = replace(schedule, open_at=override.open_at, close_at=override.close_at)
        return DayPlan(SHORT, short, override.note)
    if holiday is not None:
        return DayPlan(HOLIDAY, None, "", holiday)
    if d.weekday() not in schedule.workdays:
        return DayPlan("weekend", None)
    return DayPlan("work", schedule)


def _booking_start(day_schedule: Schedule, d: date) -> datetime:
    return datetime.combine(d, day_schedule.open_at) - timedelta(minutes=BOOKING_LEAD_MINUTES)


def can_take_ticket(now: datetime, schedule: Schedule = DEFAULT_SCHEDULE,
                    overrides: dict[date, DayOverride] | None = None) -> bool:
    """Студент қазір талон ала ма?

    Жұмыс күні, жұмыс басталардан 15 минут бұрыннан (08:45) жұмыс аяқталғанға дейін (18:00),
    түскі және қысқа үзілістерден басқа уақытта. 18:00-ден кейін келесі жұмыс күнін күту керек.
    """
    plan = day_plan(now.date(), schedule, overrides)
    if plan.schedule is None:
        return False
    s = plan.schedule
    if now < _booking_start(s, now.date()) or now.time() >= s.close_at:
        return False
    return current_pause(now, s) is None


def _pauses(s: Schedule) -> list[tuple[time, time]]:
    lunch = [(s.lunch_from, s.lunch_to)] if s.lunch_from else []
    return sorted(lunch + list(s.breaks))


def next_booking_time(now: datetime, schedule: Schedule = DEFAULT_SCHEDULE,
                      overrides: dict[date, DayOverride] | None = None,
                      horizon_days: int = 60) -> datetime | None:
    """Талон алу қашан басталады (қазір беріліп жатса — now). Мысалы, кешкі 19:00-де —
    келесі жұмыс күнінің 08:45-і, түскі үзілісте — үзіліс аяқталатын уақыт."""
    if can_take_ticket(now, schedule, overrides):
        return now
    today = day_plan(now.date(), schedule, overrides).schedule
    if today is not None and now.time() < today.close_at:
        start = _booking_start(today, now.date())
        if now < start:
            return start
        ends = [end for a, end in _pauses(today) if a <= now.time() < end]
        if ends and ends[0] < today.close_at:
            return datetime.combine(now.date(), ends[0])
    for i in range(1, horizon_days + 1):
        d = now.date() + timedelta(days=i)
        plan = day_plan(d, schedule, overrides)
        if plan.schedule is not None:
            return _booking_start(plan.schedule, d)
    return None


def month_calendar(year: int, month: int, today: date, schedule: Schedule = DEFAULT_SCHEDULE,
                   overrides: dict[date, DayOverride] | None = None) -> list[list[dict | None]]:
    """Айдың күнтізбесі: апталар тізімі (дүйсенбіден басталады), бос ұяшық — None.

    Әр күн: {'date', 'day', 'when': 'past'|'today'|'future', 'plan': DayPlan}.
    """
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for d in week:
            if d.month != month:
                row.append(None)
                continue
            when = "past" if d < today else "today" if d == today else "future"
            row.append({"date": d, "day": d.day, "when": when,
                        "plan": day_plan(d, schedule, overrides)})
        weeks.append(row)
    return weeks


# ---------------------------------------------------------------------------
# Хабарландырулар және профиль деректері
# ---------------------------------------------------------------------------
ANNOUNCEMENT_MIN, ANNOUNCEMENT_MAX = 5, 600


@dataclass(frozen=True)
class Announcement:
    text: str
    start: date
    end: date


def build_announcement(text: str, start: str, end: str, today: date) -> Announcement:
    """Хабарландыру мәтіні 5–600 таңба; көрсету мерзімі: бастап — дейін (бос болса бүгін)."""
    text = (text or "").strip()
    if not ANNOUNCEMENT_MIN <= len(text) <= ANNOUNCEMENT_MAX:
        raise QueueError("err_announcement")
    try:
        a = date.fromisoformat(start.strip()) if (start or "").strip() else today
        b = date.fromisoformat(end.strip()) if (end or "").strip() else a
    except ValueError:
        raise QueueError("err_date")
    if b < a:
        raise QueueError("err_date_order")
    return Announcement(text, a, b)


PHONE_JUNK_RE = re.compile(r"[\s\-()]")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
GENDERS = ("", "male", "female")


def normalize_phone(phone: str) -> str:
    """Қазақстан нөмірі: '8 701 234 56 78' / '+77012345678' -> '+7 701 234 56 78'. Бос -> ''."""
    raw = PHONE_JUNK_RE.sub("", phone or "")
    if not raw:
        return ""
    if raw.startswith("8") and len(raw) == 11:
        raw = "+7" + raw[1:]
    if not re.fullmatch(r"\+7\d{10}", raw):
        raise QueueError("err_phone")
    d = raw[2:]
    return f"+7 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}"


def detect_image_type(data: bytes) -> str:
    """Сурет түрін файлдың алғашқы байттары бойынша анықтайды: 'jpg' | 'png' | 'webp'.
    Файл атауы мен браузер жіберген түрге сенбейміз (басқа файлды сурет деп жіберуге болады)."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise QueueError("err_avatar_type")


def validate_group(group_name: str, errors: list[str] | None = None) -> str:
    """Топ атауы міндетті емес; жазылса, пішімі тексеріледі (мысалы, ИС-24-1)."""
    group_name = (group_name or "").strip().upper()
    if group_name and not GROUP_RE.match(group_name):
        if errors is None:
            raise QueueError("err_group")
        errors.append("err_group")
    return group_name


def validate_full_name(full_name: str) -> str:
    """Аты-жөнін тексереді (тіркелудегі ереже бойынша)."""
    full_name = " ".join((full_name or "").split())
    if not NAME_RE.match(full_name):
        raise QueueError("err_name")
    return full_name


def validate_profile(phone: str, gender: str, email: str) -> dict:
    """Профиль өрістерін тексереді. Барлығы міндетті емес; қате болса QueueError."""
    email = (email or "").strip()
    if email and (len(email) > 120 or not EMAIL_RE.match(email)):
        raise QueueError("err_email")
    gender = (gender or "").strip()
    if gender not in GENDERS:
        raise QueueError("err_gender")
    return {"phone": normalize_phone(phone), "gender": gender, "email": email.lower()}


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
    return min(pool, key=lambda t: (-int(t.get("priority", 0)), t["created_at"], t["id"]))
