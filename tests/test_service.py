"""Бизнес-логика модулінің тесттері: қалыпты, шеткі және қате жағдайлар."""
from datetime import datetime

import pytest

from app import service as ql


# ---------------- Талон нөмірі ----------------
@pytest.mark.parametrize("code,seq,expected", [
    ("A", 1, "A-001"), ("b", 42, "B-042"), ("C", 999, "C-999"),
])
def test_format_ticket_number(code, seq, expected):
    assert ql.format_ticket_number(code, seq) == expected


@pytest.mark.parametrize("code,seq", [("", 1), ("A1", 1), ("ABC", 1), ("A", 0), ("A", 1000), ("A", -5)])
def test_format_ticket_number_invalid(code, seq):
    with pytest.raises(ql.QueueError):
        ql.format_ticket_number(code, seq)


def test_next_sequence_starts_from_one_each_day():
    assert ql.next_sequence(None) == 1
    assert ql.next_sequence(0) == 1
    assert ql.next_sequence(41) == 42


def test_next_sequence_daily_limit():
    assert ql.next_sequence(998) == 999
    with pytest.raises(ql.QueueError) as e:
        ql.next_sequence(999)
    assert e.value.code == "err_daily_limit"


# ---------------- Форманы тексеру ----------------
def test_validate_ok_and_normalizes():
    req, errors = ql.validate_ticket_request("  Айгерім   Сәрсенова ", " 12345678 ", "ис-21-1", "2")
    assert errors == []
    assert req.full_name == "Айгерім Сәрсенова"
    assert req.student_id == "12345678"
    assert req.group_name == "ИС-21-1"
    assert req.service_id == 2


def test_validate_group_optional():
    req, errors = ql.validate_ticket_request("Иван Петров", "123456", "", 1)
    assert errors == [] and req.group_name == ""


@pytest.mark.parametrize("name,sid,group,service,err", [
    ("", "123456", "", 1, "err_name"),
    ("Ab", "123456", "", 1, "err_name"),                 # тым қысқа
    ("<script>", "123456", "", 1, "err_name"),           # HTML белгілері
    ("A" * 81, "123456", "", 1, "err_name"),             # тым ұзын
    ("Иван Петров", "12345", "", 1, "err_student_id"),   # 5 цифр
    ("Иван Петров", "1234567890123", "", 1, "err_student_id"),
    ("Иван Петров", "12ab56", "", 1, "err_student_id"),
    ("Иван Петров", "123456", "ИС 21", 1, "err_group"),  # бос орын
    ("Иван Петров", "123456", "", "", "err_service"),
    ("Иван Петров", "123456", "", "abc", "err_service"),
    ("Иван Петров", "123456", "", 0, "err_service"),
    ("Иван Петров", "123456", "", None, "err_service"),
])
def test_validate_errors(name, sid, group, service, err):
    req, errors = ql.validate_ticket_request(name, sid, group, service)
    assert req is None
    assert err in errors


def test_validate_none_values():
    req, errors = ql.validate_ticket_request(None, None, None, None)
    assert req is None
    assert set(errors) == {"err_name", "err_student_id", "err_service"}


# ---------------- Күту уақытының болжамы ----------------
def test_estimate_zero_people():
    assert ql.estimate_wait_minutes(0, 5, 2) == 0


def test_estimate_one_window():
    assert ql.estimate_wait_minutes(3, 5, 1) == 15


def test_estimate_several_windows_rounds_up():
    # 5 адам, 2 терезе -> 3 «айналым» * 4 мин = 12
    assert ql.estimate_wait_minutes(5, 4, 2) == 12


def test_estimate_no_windows_counts_as_one():
    assert ql.estimate_wait_minutes(2, 5, 0) == 10


def test_estimate_fractional_minutes_rounded_up():
    assert ql.estimate_wait_minutes(1, 4.2, 1) == 5


@pytest.mark.parametrize("people,avg", [(-1, 5), (1, 0), (1, -3)])
def test_estimate_invalid(people, avg):
    with pytest.raises(ql.QueueError):
        ql.estimate_wait_minutes(people, avg, 1)


def test_average_duration_uses_default_when_few_samples():
    assert ql.average_duration([], 6) == 6
    assert ql.average_duration([3, 4], 6) == 6


def test_average_duration_blends_real_data():
    # орташа 4, әдепкі 6 -> 0.8*4 + 0.2*6 = 4.4
    assert ql.average_duration([3, 4, 5], 6) == 4.4


def test_average_duration_ignores_outliers():
    # 0 және 500 минут есепке алынбайды -> қалғаны 2 мән < 3 -> әдепкі
    assert ql.average_duration([0, 500, 4, 4], 6) == 6


# ---------------- Жұмыс уақыты ----------------
@pytest.mark.parametrize("dt,expected", [
    (datetime(2026, 11, 16, 9, 0), True),     # дс 09:00 — ашылды
    (datetime(2026, 11, 16, 8, 59), False),   # ашылғанға дейін
    (datetime(2026, 11, 16, 13, 0), False),   # түскі үзіліс басы
    (datetime(2026, 11, 16, 13, 59), False),
    (datetime(2026, 11, 16, 14, 0), True),    # үзілістен кейін
    (datetime(2026, 11, 16, 17, 59), True),
    (datetime(2026, 11, 16, 18, 0), False),   # жабылды
    (datetime(2026, 11, 14, 10, 0), False),   # сенбі
    (datetime(2026, 11, 15, 10, 0), False),   # жексенбі
])
def test_is_open(dt, expected):
    assert ql.is_open(dt) is expected


def test_minutes_until_close_and_late_warning():
    now = datetime(2026, 11, 16, 17, 30)
    assert ql.minutes_until_close(now) == 30
    assert ql.can_be_served_today(now, 30) is True
    assert ql.can_be_served_today(now, 31) is False
    assert ql.minutes_until_close(datetime(2026, 11, 16, 19, 0)) == 0


# ---------------- Күй өтулері ----------------
@pytest.mark.parametrize("a,b,ok", [
    (ql.WAITING, ql.CALLED, True),
    (ql.WAITING, ql.CANCELLED, True),
    (ql.CALLED, ql.DONE, True),
    (ql.CALLED, ql.NO_SHOW, True),
    (ql.CALLED, ql.WAITING, True),
    (ql.WAITING, ql.DONE, False),       # шақырмай аяқтауға болмайды
    (ql.DONE, ql.CALLED, False),        # аяқталған талонды қайта ашуға болмайды
    (ql.CANCELLED, ql.WAITING, False),
    (ql.CALLED, ql.CANCELLED, False),
    ("unknown", ql.CALLED, False),
])
def test_transitions(a, b, ok):
    assert ql.can_transition(a, b) is ok


def test_ensure_transition_raises():
    with pytest.raises(ql.QueueError) as e:
        ql.ensure_transition(ql.DONE, ql.WAITING)
    assert e.value.code == "err_bad_transition"


# ---------------- Келесі талонды таңдау ----------------
def _t(i, sid, created, prio=0):
    return {"id": i, "service_id": sid, "created_at": created, "priority": prio}


def test_pick_next_fifo():
    q = [_t(2, 1, "2026-11-16 10:05:00"), _t(1, 1, "2026-11-16 10:01:00")]
    assert ql.pick_next(q)["id"] == 1


def test_pick_next_priority_first():
    q = [_t(1, 1, "2026-11-16 10:01:00"), _t(2, 1, "2026-11-16 10:09:00", prio=1)]
    assert ql.pick_next(q)["id"] == 2


def test_pick_next_filters_by_service():
    q = [_t(1, 1, "2026-11-16 10:01:00"), _t(2, 3, "2026-11-16 10:02:00")]
    assert ql.pick_next(q, {3})["id"] == 2
    assert ql.pick_next(q, {5}) is None


def test_pick_next_same_time_uses_id():
    q = [_t(7, 1, "2026-11-16 10:00:00"), _t(3, 1, "2026-11-16 10:00:00")]
    assert ql.pick_next(q)["id"] == 3


def test_pick_next_empty():
    assert ql.pick_next([]) is None


# ---------------- Тіркелу және құпиясөз ----------------
@pytest.mark.parametrize("pw,ok", [
    ("Abcdefg1", True), ("Пароль2026", True), ("dana#2005", True),
    ("abcdefg1", False),        # әлсіз: тек кіші әріп пен цифр
    ("Abc1", False),            # тым қысқа
    ("Abcdefgh", False),        # цифр жоқ
    ("12345678", False),        # әріп жоқ
    ("", False), (None, False),
    ("Aa1" * 6, False),         # 16-дан ұзын
    ("Abcd 1234", False),       # бос орын
])
def test_validate_password(pw, ok):
    assert (ql.validate_password(pw) == []) is ok


def test_password_mismatch():
    assert "err_password_mismatch" in ql.validate_password("Abcdefg1", "Abcdefg2")


def test_register_student_ok():
    reg, errors = ql.validate_registration("student", " Дана  Серікқызы ", "Parol2026",
                                           "Parol2026", " 050720610008 ", "эк-23-2")
    assert errors == []
    assert reg.role == "student" and reg.username == "050720610008"
    assert reg.full_name == "Дана Серікқызы" and reg.group_name == "ЭК-23-2"


def test_register_student_needs_only_name_login_password():
    """Тіркелуде міндетті: аты-жөні, логин, құпиясөз. Тобы — міндетті емес (профильде)."""
    reg, errors = ql.validate_registration("student", "Дана Серікқызы", "Parol2026", "Parol2026",
                                           username="Dana.S")
    assert errors == [] and reg.username == "dana.s" and reg.student_id == "dana.s" and reg.group_name == ""
    _, errors = ql.validate_registration("student", "Дана Серікқызы", "Parol2026", "Parol2026", "12", "!!")
    assert {"err_username", "err_group"} <= set(errors)
    _, errors = ql.validate_registration("student", "", "Parol2026", "Parol2026", username="dana.s")
    assert "err_name" in errors


def test_register_dekanat_ok_and_username_lowercased():
    reg, errors = ql.validate_registration("dekanat", "Жанар Сейітова", "Parol2026",
                                           "Parol2026", username="J.Seitova")
    assert errors == [] and reg.username == "j.seitova" and reg.student_id is None


@pytest.mark.parametrize("username", ["ab", "with space", "кирилл", "a" * 31, "x;drop"])
def test_register_dekanat_bad_username(username):
    _, errors = ql.validate_registration("dekanat", "Жанар Сейітова", "Parol2026",
                                         "Parol2026", username=username)
    assert "err_username" in errors


@pytest.mark.parametrize("kind", ["dekanat", "deputy", "admin"])
def test_register_staff_roles_allowed(kind):
    reg, errors = ql.validate_registration(kind, "Жаңа Қызметкер", "Parol2026", "Parol2026",
                                           username="newstaff")
    assert errors == [] and reg.role == kind and reg.student_id is None


def test_register_unknown_role_rejected():
    reg, errors = ql.validate_registration("superuser", "Хакер Хакеров", "Parol2026", "Parol2026",
                                           username="hacker")
    assert reg is None and errors == ["err_role"]


def test_parse_period_and_summary():
    from datetime import date
    s, e = ql.parse_period("", "", date(2026, 11, 16))
    assert (s, e) == (date(2026, 11, 10), date(2026, 11, 16))
    for bad in (("2026-11-20", "2026-11-01"), ("x", ""), ("2024-01-01", "2026-01-01")):
        with pytest.raises(ql.QueueError):
            ql.parse_period(*bad, date(2026, 11, 16))
    rows = [{"status": "done", "created_at": "2026-11-16 10:00:00", "called_at": "2026-11-16 10:06:00",
             "finished_at": "2026-11-16 10:10:00", "window_no": 2, "day": "2026-11-16", "name_kk": "A"},
            {"status": "no_show", "created_at": "2026-11-16 10:01:00", "called_at": None,
             "finished_at": None, "window_no": None, "day": "2026-11-16", "name_kk": "A"}]
    rep = ql.summarize_tickets(rows)
    assert rep["summary"]["total"] == 2 and rep["summary"]["avg_wait"] == 6.0 and rep["summary"]["avg_service"] == 4.0
    assert [g["key"] for g in rep["by_window"]] == [2, "—"]
    assert ql.matches("ЗАМ", "Заместитель") and ql.matches("", "x") and not ql.matches("q", None)
