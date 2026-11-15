"""Декан орынбасары, қызметкер үзілісі, жұмыс кестесін сақтау және миграция (db.py)."""
import pytest
from conftest import MONDAY_10

from app import db as repo
from app import service as ql


def uid(conn, username):
    return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]


def student(conn, sid="040215410000"):
    reg, errors = ql.validate_registration("student", "Дана Серікқызы", "Parol2026", "Parol2026", sid, "ЭК-23-2")
    assert not errors
    return repo.get_user(conn, repo.register(conn, reg, MONDAY_10))


def test_schedule_default_and_save(conn):
    assert repo.get_schedule(conn) == ql.DEFAULT_SCHEDULE
    new = ql.build_schedule("08:00", "16:00", "12:00", "12:45", "10:00-10:10", [0, 1, 2, 3, 4, 5])
    repo.save_schedule(conn, uid(conn, "zamdekan"), new, MONDAY_10)
    assert repo.get_schedule(conn) == new
    assert any(a["action"] == "schedule" for a in repo.list_audit(conn))


def test_schedule_save_rights(conn):
    repo.save_schedule(conn, uid(conn, "dekanat1"), ql.DEFAULT_SCHEDULE, MONDAY_10)  # декан — болады
    with pytest.raises(ql.QueueError) as e:
        repo.save_schedule(conn, student(conn)["id"], ql.DEFAULT_SCHEDULE, MONDAY_10)
    assert e.value.code == "err_forbidden"


def test_broken_schedule_falls_back_to_default(conn):
    conn.execute("INSERT INTO settings VALUES ('schedule', '{not json')")
    assert repo.get_schedule(conn) == ql.DEFAULT_SCHEDULE


def test_ticket_refused_during_custom_break(conn):
    new = ql.build_schedule("09:00", "18:00", "", "", "10:00-10:20", [0, 1, 2, 3, 4])
    repo.save_schedule(conn, uid(conn, "admin"), new, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, student(conn), 1, MONDAY_10.replace(minute=5))
    assert e.value.code == "err_closed"


def test_staff_break_blocks_calls_and_windows(conn):
    op = uid(conn, "dekanat1")
    repo.set_on_duty(conn, op, True)
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    assert repo.active_windows(conn, 1) == 1
    repo.set_break(conn, op, True, MONDAY_10)
    assert repo.active_windows(conn, 1) == 0
    with pytest.raises(ql.QueueError) as e:
        repo.call_next(conn, op, MONDAY_10)
    assert e.value.code == "err_on_break"
    assert {"window_no": "2", "on_break": True} in repo.board_data(conn, MONDAY_10)["windows"]
    repo.set_break(conn, op, False, MONDAY_10)
    assert repo.call_next(conn, op, MONDAY_10) is not None


def test_cannot_break_with_called_student(conn):
    op = uid(conn, "dekanat1")
    repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    repo.call_next(conn, op, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.set_break(conn, op, True, MONDAY_10)
    assert e.value.code == "err_finish_current"


def test_student_cannot_take_break(conn):
    with pytest.raises(ql.QueueError):
        repo.set_break(conn, student(conn)["id"], True, MONDAY_10)


def test_logout_ends_break(conn):
    op = uid(conn, "dekanat1")
    repo.set_on_duty(conn, op, True)
    repo.set_break(conn, op, True, MONDAY_10)
    repo.set_on_duty(conn, op, False)
    assert repo.get_user(conn, op)["on_break"] == 0


def test_deputy_does_dean_work(conn):
    deputy = uid(conn, "zamdekan")
    reg, _ = ql.validate_registration("deputy", "Жаңа Орынбасар", "Parol2026", "Parol2026", username="newstaff")
    new_id = repo.register(conn, reg, MONDAY_10)
    repo.admin_set_active(conn, deputy, new_id, True, MONDAY_10)
    repo.admin_update_staff(conn, deputy, new_id, "5", ["1"], MONDAY_10)
    repo.admin_set_role(conn, deputy, new_id, "deputy", MONDAY_10)
    t = repo.create_ticket(conn, student(conn), 1, MONDAY_10)
    repo.admin_set_ticket_status(conn, deputy, t["id"], ql.CANCELLED, MONDAY_10)
    repo.admin_save_service(conn, deputy, None, "G", "Жаңа", "Новая", 5, True, MONDAY_10)
    assert repo.get_user(conn, new_id)["role"] == "deputy"


def test_deputy_cannot_touch_dean(conn):
    deputy, admin = uid(conn, "zamdekan"), uid(conn, "admin")
    actions = (lambda: repo.admin_set_active(conn, deputy, admin, False, MONDAY_10),
               lambda: repo.admin_reset_password(conn, deputy, admin, "Hack2026x", MONDAY_10),
               lambda: repo.admin_delete_user(conn, deputy, admin, MONDAY_10),
               lambda: repo.admin_set_role(conn, deputy, uid(conn, "dekanat1"), "admin", MONDAY_10))
    for fn in actions:
        with pytest.raises(ql.QueueError) as e:
            fn()
        assert e.value.code == "err_forbidden"


def test_student_cannot_use_manager_functions(conn):
    st = student(conn)
    me = st["id"]
    t = repo.create_ticket(conn, st, 1, MONDAY_10)
    for fn in (lambda: repo.admin_set_active(conn, me, uid(conn, "dekanat1"), False, MONDAY_10),
               lambda: repo.admin_set_ticket_status(conn, me, t["id"], ql.DONE, MONDAY_10),
               lambda: repo.admin_delete_ticket(conn, me, t["id"], MONDAY_10)):
        with pytest.raises(ql.QueueError):
            fn()


def test_hierarchy_admin_dekan_deputy_student(conn):
    """Иерархия: администратор > декан > декан орынбасары > студент."""
    dekan, deputy, admin = uid(conn, "dekanat1"), uid(conn, "zamdekan"), uid(conn, "admin")
    # Декан орынбасарын және студентті басқарады, бірақ администраторды — жоқ
    repo.admin_set_active(conn, dekan, deputy, False, MONDAY_10)
    repo.admin_set_active(conn, dekan, deputy, True, MONDAY_10)
    repo.admin_set_active(conn, dekan, uid(conn, "030512501238"), False, MONDAY_10)
    for fn in (lambda: repo.admin_set_active(conn, dekan, admin, False, MONDAY_10),
               lambda: repo.admin_set_role(conn, dekan, deputy, "admin", MONDAY_10)):
        with pytest.raises(ql.QueueError) as e:
            fn()
        assert e.value.code == "err_forbidden"
    # Орынбасар деканның өтінімін растай алмайды — тек администратор
    reg, _ = ql.validate_registration("dekanat", "Жаңа Декан", "Parol2026", "Parol2026", username="newdekan")
    new_id = repo.register(conn, reg, MONDAY_10)
    with pytest.raises(ql.QueueError):
        repo.admin_set_active(conn, deputy, new_id, True, MONDAY_10)
    repo.admin_set_active(conn, admin, new_id, True, MONDAY_10)
    assert repo.get_user(conn, new_id)["is_active"]
    assert ql.ROLES == ("admin", "dekanat", "deputy", "student")


def test_deputy_can_call_students(conn):
    repo.create_ticket(conn, student(conn), 3, MONDAY_10)
    assert repo.call_next(conn, uid(conn, "zamdekan"), MONDAY_10)["window_no"] == "4"


def test_migration_from_old_schema(tmp_path):
    """Ескі дерекқор (deputy рөлі мен on_break бағаны жоқ) деректерін жоғалтпай жаңарады."""
    path = tmp_path / "old.db"
    old = repo.connect(path)
    old_schema = repo.SCHEMA.replace("('student','dekanat','deputy','admin')", "('student','dekanat','admin')")
    old_schema = old_schema.replace("    on_break      INTEGER NOT NULL DEFAULT 0,      -- қызметкер үзілісте ме\n", "")
    assert "on_break" not in old_schema.split("CREATE TABLE IF NOT EXISTS settings")[0]
    old.executescript(old_schema)
    old.execute("INSERT INTO users (username, password_hash, full_name, role, created_at) "
                "VALUES ('olduser', 'x', 'Ескі Қолданушы', 'dekanat', '2026-01-01 00:00:00')")
    old.close()
    conn = repo.connect(path)
    repo.init_db(conn)
    repo.seed(conn, MONDAY_10)
    assert conn.execute("SELECT full_name FROM users WHERE username='olduser'").fetchone()[0] == "Ескі Қолданушы"
    assert conn.execute("SELECT on_break FROM users WHERE username='olduser'").fetchone()[0] == 0
    assert conn.execute("SELECT 1 FROM users WHERE role='deputy'").fetchone()
    repo.init_db(conn)  # қайта шақырғанда ештеңе бұзылмайды
