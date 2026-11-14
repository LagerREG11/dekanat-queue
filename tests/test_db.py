"""Дерекқор деңгейінің тесттері (SQLite жадта)."""
from datetime import timedelta

import pytest
from conftest import MONDAY_10

from app import db as repo
from app import service as ql


def uid(conn, username):
    return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]


def student(conn, sid="20230001", name="Дана Серікқызы", group="ЭК-23-2"):
    """Жаңа студент тіркейді және оның жолын қайтарады."""
    reg, errors = ql.validate_registration("student", name, "Parol2026", "Parol2026", sid, group)
    assert not errors
    return repo.get_user(conn, repo.register(conn, reg, MONDAY_10))


# ---------------- Схема және демо-деректер ----------------
def test_schema_has_required_tables(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"services", "users", "tickets", "user_services", "audit_log"} <= names


def test_seed_is_idempotent_and_has_all_roles(conn):
    repo.seed(conn, MONDAY_10)
    roles = {r[0] for r in conn.execute("SELECT role FROM users")}
    assert roles == {"student", "dekanat", "deputy", "admin"}
    assert conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 5


def test_role_check_constraint(conn):
    with pytest.raises(Exception):
        conn.execute("INSERT INTO users (username, password_hash, full_name, role, created_at) "
                     "VALUES ('x','h','X','superuser','2026-01-01 00:00:00')")


# ---------------- Тіркелу және кіру ----------------
def test_passwords_are_hashed(conn):
    row = conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()
    assert "Admin2026" not in row[0]


def test_authenticate_each_role(conn):
    for username, pw, role in [("20210001", "Student2026", "student"),
                               ("dekanat1", "Dekanat2026", "dekanat"),
                               ("admin", "Admin2026", "admin")]:
        user, err = repo.authenticate(conn, username, pw, role)
        assert err is None and user["role"] == role


def test_authenticate_errors(conn):
    assert repo.authenticate(conn, "admin", "wrong")[1] == "err_login"
    assert repo.authenticate(conn, "nobody", "Admin2026")[1] == "err_login"
    assert repo.authenticate(conn, "", "")[1] == "err_login"
    # дұрыс құпиясөз, бірақ басқа қойынды
    assert repo.authenticate(conn, "admin", "Admin2026", "student")[1] == "err_wrong_role"
    # логин регистрге тәуелсіз
    assert repo.authenticate(conn, "ADMIN", "Admin2026", "admin")[1] is None


def test_student_registration_active_immediately(conn):
    s = student(conn)
    assert s["role"] == "student" and s["is_active"] == 1 and s["username"] == "20230001"
    assert repo.authenticate(conn, "20230001", "Parol2026", "student")[1] is None


def test_staff_registration_needs_approval(conn):
    reg, _ = ql.validate_registration("dekanat", "Жанар Сейітова", "Parol2026", "Parol2026",
                                      username="jseitova")
    new_id = repo.register(conn, reg, MONDAY_10)
    assert repo.authenticate(conn, "jseitova", "Parol2026", "dekanat")[1] == "err_inactive"
    repo.admin_set_active(conn, uid(conn, "admin"), new_id, True, MONDAY_10)
    assert repo.authenticate(conn, "jseitova", "Parol2026", "dekanat")[1] is None
    assert repo.count_pending(conn) == 0


def test_duplicate_registration(conn):
    student(conn)
    with pytest.raises(ql.QueueError) as e:
        student(conn)
    assert e.value.code == "err_username_taken"


def test_change_password(conn):
    s = student(conn)
    with pytest.raises(ql.QueueError) as e:
        repo.change_password(conn, s["id"], "wrong", "NewPass1", "NewPass1", MONDAY_10)
    assert e.value.code == "err_old_password"
    with pytest.raises(ql.QueueError):
        repo.change_password(conn, s["id"], "Parol2026", "short", "short", MONDAY_10)
    repo.change_password(conn, s["id"], "Parol2026", "NewPass1", "NewPass1", MONDAY_10)
    assert repo.authenticate(conn, s["username"], "NewPass1")[1] is None


# ---------------- Әкімші: аккаунттар ----------------
def test_admin_block_user(conn):
    admin = uid(conn, "admin")
    s = student(conn)
    repo.admin_set_active(conn, admin, s["id"], False, MONDAY_10)
    assert repo.authenticate(conn, s["username"], "Parol2026")[1] == "err_inactive"
    assert any(a["action"] == "block" for a in repo.list_audit(conn))


def test_admin_cannot_block_or_delete_self(conn):
    admin = uid(conn, "admin")
    for fn in (lambda: repo.admin_set_active(conn, admin, admin, False, MONDAY_10),
               lambda: repo.admin_delete_user(conn, admin, admin, MONDAY_10)):
        with pytest.raises(ql.QueueError) as e:
            fn()
        assert e.value.code == "err_self"


def test_last_admin_protected(conn):
    admin = uid(conn, "admin")
    second = repo.create_user(conn, "admin2", "Admin2026", "Екінші әкімші", "admin", now=MONDAY_10)
    # екінші әкімші біріншіні бұғаттай алады (әкімшілер екеу)
    repo.admin_set_active(conn, second, admin, False, MONDAY_10)
    # енді admin2 — жалғыз әкімші; оны рөлінен айыру мүмкін емес
    repo.admin_set_active(conn, second, admin, True, MONDAY_10)
    repo.admin_set_role(conn, admin, second, "dekanat", MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.admin_set_role(conn, second, admin, "dekanat", MONDAY_10)
    assert e.value.code in ("err_last_admin", "err_forbidden")


def test_admin_change_role(conn):
    admin = uid(conn, "admin")
    d = uid(conn, "dekanat1")
    repo.admin_set_role(conn, admin, d, "admin", MONDAY_10)
    assert repo.get_user(conn, d)["role"] == "admin"
    with pytest.raises(ql.QueueError):  # студент рөліне студенттік ID керек
        repo.admin_set_role(conn, admin, d, "student", MONDAY_10)
    with pytest.raises(ql.QueueError):
        repo.admin_set_role(conn, admin, d, "god", MONDAY_10)


def test_admin_reset_password(conn):
    admin = uid(conn, "admin")
    s = student(conn)
    with pytest.raises(ql.QueueError):
        repo.admin_reset_password(conn, admin, s["id"], "123", MONDAY_10)
    repo.admin_reset_password(conn, admin, s["id"], "Reset2026", MONDAY_10)
    assert repo.authenticate(conn, s["username"], "Reset2026")[1] is None


def test_admin_update_staff(conn):
    admin = uid(conn, "admin")
    d = uid(conn, "dekanat1")
    repo.admin_update_staff(conn, admin, d, "7", ["1", "3", "999", "x"], MONDAY_10)
    assert repo.get_user(conn, d)["window_no"] == 7
    assert repo.user_service_ids(conn, d) == {1, 3}  # жоқ және қате id-лер еленбейді
    for bad in ("0", "100", "abc", None):
        with pytest.raises(ql.QueueError):
            repo.admin_update_staff(conn, admin, d, bad, [], MONDAY_10)


def test_admin_delete_user_keeps_tickets(conn):
    admin = uid(conn, "admin")
    s = student(conn)
    t = repo.create_ticket(conn, s, 1, MONDAY_10)
    repo.admin_delete_user(conn, admin, s["id"], MONDAY_10)
    assert repo.get_user(conn, s["id"]) is None
    assert repo.get_ticket(conn, t["id"])["user_id"] is None


# ---------------- Әкімші: қызметтер ----------------
def test_admin_create_and_update_service(conn):
    admin = uid(conn, "admin")
    sid = repo.admin_save_service(conn, admin, None, "f", "Стипендия", "Стипендия", "5", True, MONDAY_10)
    assert repo.get_service(conn, sid)["code"] == "F"
    repo.admin_save_service(conn, admin, sid, "F", "Стипендия", "Стипендия", "9", False, MONDAY_10)
    assert repo.get_service(conn, sid)["is_active"] == 0
    assert sid not in {s["id"] for s in repo.list_services(conn)}


@pytest.mark.parametrize("code,kk,ru,avg,err", [
    ("A", "Жаңа", "Новая", 5, "err_service_code_taken"),
    ("1", "Жаңа", "Новая", 5, "err_bad_service_code"),
    ("ABC", "Жаңа", "Новая", 5, "err_bad_service_code"),
    ("G", "Ж", "Новая", 5, "err_service_name"),
    ("G", "Жаңа", "Новая", 0, "err_avg"),
    ("G", "Жаңа", "Новая", 500, "err_avg"),
    ("G", "Жаңа", "Новая", "abc", "err_avg"),
])
def test_admin_service_validation(conn, code, kk, ru, avg, err):
    with pytest.raises(ql.QueueError) as e:
        repo.admin_save_service(conn, uid(conn, "admin"), None, code, kk, ru, avg, True, MONDAY_10)
    assert e.value.code == err


# ---------------- Талондар ----------------
def test_ticket_numbers_increment_per_service(conn):
    a, b = student(conn, "111111"), student(conn, "222222")
    a1 = repo.create_ticket(conn, a, 1, MONDAY_10)
    a2 = repo.create_ticket(conn, b, 1, MONDAY_10)
    b1 = repo.create_ticket(conn, a, 2, MONDAY_10)
    assert (a1["number"], a2["number"], b1["number"]) == ("A-001", "A-002", "B-001")
    assert a1["full_name"] == "Дана Серікқызы" and a1["student_id"] == "111111"
    assert a1["token"] != a2["token"] and len(a1["token"]) >= 16


def test_numbers_reset_next_day(conn):
    s = student(conn)
    repo.create_ticket(conn, s, 1, MONDAY_10)
    assert repo.create_ticket(conn, s, 1, MONDAY_10 + timedelta(days=1))["number"] == "A-001"


def test_only_active_students_can_take_tickets(conn):
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, repo.get_user(conn, uid(conn, "dekanat1")), 1, MONDAY_10)
    assert e.value.code == "err_forbidden"
    with pytest.raises(ql.QueueError):
        repo.create_ticket(conn, None, 1, MONDAY_10)


def test_duplicate_active_ticket_rejected(conn):
    s = student(conn)
    repo.create_ticket(conn, s, 1, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, s, 1, MONDAY_10)
    assert e.value.code == "err_already_in_queue"


def test_max_three_active_tickets(conn):
    s = student(conn)
    for sid in (1, 2, 3):
        repo.create_ticket(conn, s, sid, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, s, 4, MONDAY_10)
    assert e.value.code == "err_too_many"


def test_closed_hours_rejected(conn):
    s = student(conn)
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, s, 1, MONDAY_10.replace(hour=13, minute=30))
    assert e.value.code == "err_closed"
    assert repo.create_ticket(conn, s, 1, MONDAY_10.replace(hour=20), check_hours=False)


@pytest.mark.parametrize("service", [99, "abc", None, 0])
def test_unknown_service(conn, service):
    with pytest.raises(ql.QueueError):
        repo.create_ticket(conn, student(conn), service, MONDAY_10)


def test_inactive_service(conn):
    conn.execute("UPDATE services SET is_active=0 WHERE id=1")
    with pytest.raises(ql.QueueError):
        repo.create_ticket(conn, student(conn), 1, MONDAY_10)


def test_people_ahead_and_estimate(conn):
    tickets = [repo.create_ticket(conn, student(conn, str(100000 + i)), 1,
                                  MONDAY_10 + timedelta(seconds=i)) for i in range(4)]
    assert [repo.people_ahead(conn, t) for t in tickets] == [0, 1, 2, 3]
    assert repo.estimate_for_service(conn, repo.get_service(conn, 1), 3) == 12


def test_priority_ticket_goes_first(conn):
    normal = repo.create_ticket(conn, student(conn, "111111"), 1, MONDAY_10)
    prio = repo.create_ticket(conn, student(conn, "222222"), 1, MONDAY_10 + timedelta(minutes=1),
                              priority=True)
    assert repo.people_ahead(conn, prio) == 0
    assert repo.people_ahead(conn, repo.get_ticket(conn, normal["id"])) == 1


def test_cancel_ticket_only_by_owner(conn):
    s, other = student(conn, "111111"), student(conn, "222222")
    t = repo.create_ticket(conn, s, 1, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.cancel_ticket(conn, t["id"], other["id"], MONDAY_10)
    assert e.value.code == "err_forbidden"
    repo.cancel_ticket(conn, t["id"], s["id"], MONDAY_10)
    assert repo.get_ticket(conn, t["id"])["status"] == "cancelled"
    with pytest.raises(ql.QueueError):
        repo.cancel_ticket(conn, t["id"], s["id"], MONDAY_10)
    with pytest.raises(ql.QueueError):
        repo.cancel_ticket(conn, 9999, s["id"], MONDAY_10)
    assert repo.create_ticket(conn, s, 1, MONDAY_10)["number"] == "A-002"


def test_user_tickets_history(conn):
    s = student(conn)
    repo.create_ticket(conn, s, 1, MONDAY_10)
    repo.create_ticket(conn, s, 2, MONDAY_10)
    assert [t["number"] for t in repo.user_tickets(conn, s["id"])] == ["B-001", "A-001"]


# ---------------- Деканат қызметкері ----------------
def test_operator_flow_call_done(conn):
    op = uid(conn, "dekanat1")  # A, B, E; терезе 2
    t = repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    called = repo.call_next(conn, op, MONDAY_10 + timedelta(minutes=2))
    assert called["number"] == t["number"] and called["status"] == "called"
    assert called["window_no"] == 2
    repo.finish_ticket(conn, op, called["id"], ql.DONE, MONDAY_10 + timedelta(minutes=7))
    assert repo.get_ticket(conn, called["id"])["status"] == "done"
    assert repo.recent_durations(conn, 1) == [5.0]
    stats = repo.stats_today(conn, MONDAY_10)
    assert stats["done"] == 1 and stats["avg_wait"] == 2.0 and stats["avg_service"] == 5.0


def test_student_cannot_call(conn):
    s = student(conn)
    with pytest.raises(ql.QueueError) as e:
        repo.call_next(conn, s["id"], MONDAY_10)
    assert e.value.code == "err_forbidden"


def test_staff_without_window_cannot_call(conn):
    reg, _ = ql.validate_registration("dekanat", "Жаңа Қызметкер", "Parol2026", "Parol2026",
                                      username="newstaff")
    new_id = repo.register(conn, reg, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.call_next(conn, new_id, MONDAY_10)
    assert e.value.code == "err_window"


def test_call_next_respects_operator_services(conn):
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    assert repo.call_next(conn, uid(conn, "dekanat2"), MONDAY_10) is None  # B, C, D — A жоқ


def test_cannot_call_twice_without_finishing(conn):
    op = uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn, "111111"), 1, MONDAY_10)
    repo.create_ticket(conn, student(conn, "222222"), 1, MONDAY_10)
    repo.call_next(conn, op, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.call_next(conn, op, MONDAY_10)
    assert e.value.code == "err_finish_current"


def test_two_operators_get_different_tickets(conn):
    repo.create_ticket(conn, student(conn, "111111"), 1, MONDAY_10)
    repo.create_ticket(conn, student(conn, "222222"), 1, MONDAY_10)
    t1 = repo.call_next(conn, uid(conn, "admin"), MONDAY_10)
    t2 = repo.call_next(conn, uid(conn, "dekanat1"), MONDAY_10)
    assert t1["id"] != t2["id"]


def test_other_operator_cannot_finish_ticket(conn):
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    t = repo.call_next(conn, uid(conn, "admin"), MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.finish_ticket(conn, uid(conn, "dekanat1"), t["id"], ql.DONE, MONDAY_10)
    assert e.value.code == "err_forbidden"


def test_return_to_queue_and_no_show(conn):
    op = uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    t = repo.call_next(conn, op, MONDAY_10)
    repo.finish_ticket(conn, op, t["id"], ql.WAITING, MONDAY_10)
    assert repo.get_ticket(conn, t["id"])["status"] == "waiting"
    t = repo.call_next(conn, op, MONDAY_10)
    repo.finish_ticket(conn, op, t["id"], ql.NO_SHOW, MONDAY_10)
    with pytest.raises(ql.QueueError):  # соңғы күйден өзгертуге болмайды
        repo.finish_ticket(conn, op, t["id"], ql.DONE, MONDAY_10)


def test_recall_only_for_own_called_ticket(conn):
    op = uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    t = repo.call_next(conn, op, MONDAY_10)
    repo.recall_ticket(conn, op, t["id"])
    assert repo.get_ticket(conn, t["id"])["recall_count"] == 1
    with pytest.raises(ql.QueueError):
        repo.recall_ticket(conn, uid(conn, "admin"), t["id"])


def test_estimate_uses_active_windows(conn):
    for i in range(4):
        repo.create_ticket(conn, student(conn, str(300000 + i)), 2, MONDAY_10)
    service = repo.get_service(conn, 2)  # B: 6 мин, dekanat1 + dekanat2 + admin
    assert repo.estimate_for_service(conn, service, 4) == 24
    repo.set_on_duty(conn, uid(conn, "dekanat1"), True)
    repo.set_on_duty(conn, uid(conn, "dekanat2"), True)
    assert repo.estimate_for_service(conn, service, 4) == 12


# ---------------- Әкімші: талондарды түзету ----------------
def test_admin_fixes_wrong_status(conn):
    admin, op = uid(conn, "admin"), uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    t = repo.call_next(conn, op, MONDAY_10)
    repo.finish_ticket(conn, op, t["id"], ql.NO_SHOW, MONDAY_10)   # қате басылды
    repo.admin_set_ticket_status(conn, admin, t["id"], ql.WAITING, MONDAY_10)  # түзету
    fixed = repo.get_ticket(conn, t["id"])
    assert fixed["status"] == "waiting" and fixed["operator_id"] is None
    repo.admin_set_ticket_status(conn, admin, t["id"], ql.DONE, MONDAY_10)
    assert repo.get_ticket(conn, t["id"])["status"] == "done"
    assert any(a["action"] == "ticket_status" for a in repo.list_audit(conn))


def test_admin_status_errors(conn):
    admin = uid(conn, "admin")
    t = repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    with pytest.raises(ql.QueueError):
        repo.admin_set_ticket_status(conn, admin, t["id"], "hacked", MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.admin_set_ticket_status(conn, admin, t["id"], ql.CALLED, MONDAY_10)
    assert e.value.code == "err_admin_call"
    with pytest.raises(ql.QueueError):
        repo.admin_set_ticket_status(conn, admin, 9999, ql.DONE, MONDAY_10)


def test_admin_delete_ticket(conn):
    t = repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    repo.admin_delete_ticket(conn, uid(conn, "admin"), t["id"], MONDAY_10)
    assert repo.get_ticket(conn, t["id"]) is None


# ---------------- Табло және қауіпсіздік ----------------
def test_board_data(conn):
    op = uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn, "111111"), 1, MONDAY_10)
    repo.create_ticket(conn, student(conn, "222222"), 1, MONDAY_10)
    repo.call_next(conn, op, MONDAY_10)
    data = repo.board_data(conn, MONDAY_10)
    assert data["called"][0]["number"] == "A-001" and data["called"][0]["window_no"] == 2
    assert data["waiting"] == ["A-002"]
    assert "full_name" not in data["called"][0]


def test_sql_injection_is_harmless(conn):
    evil = "' OR 1=1 --"
    assert repo.authenticate(conn, evil, evil)[0] is None
    assert repo.get_ticket_by_token(conn, evil) is None
    assert repo.get_ticket_by_token(conn, "x" * 100) is None
