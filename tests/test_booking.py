"""Алдын ала уақыт брондау және кезек шегі (нақты кезекте 20 студент)."""
from datetime import datetime, timedelta

import pytest
from conftest import MONDAY_10, make_iin

from app import db as repo
from app import service as ql


def student(conn, n):
    reg, errors = ql.validate_registration("student", "Студент Тестов", "Parol2026", "Parol2026",
                                           make_iin(n), "ЭК-23-2")
    assert not errors
    return repo.get_user(conn, repo.register(conn, reg, MONDAY_10))


def op(conn):
    return conn.execute("SELECT id FROM users WHERE username='dekanat1'").fetchone()[0]


def test_earliest_booking_is_two_hours_later():
    assert ql.earliest_booking(datetime(2026, 11, 16, 16, 40)) == datetime(2026, 11, 16, 18, 40)
    assert ql.earliest_booking(datetime(2026, 11, 16, 10, 3)) == datetime(2026, 11, 16, 12, 10)
    assert ql.earliest_booking(datetime(2026, 11, 16, 10, 0, 30)) == datetime(2026, 11, 16, 12, 10)


@pytest.mark.parametrize("slot, err", [
    (datetime(2026, 11, 16, 11, 50), "err_book_early"),   # 2 сағаттан ерте
    (datetime(2026, 11, 16, 13, 30), "err_book_time"),    # түскі үзіліс
    (datetime(2026, 11, 16, 18, 0), "err_book_time"),     # жұмыс уақытынан тыс
    (datetime(2026, 11, 21, 10, 0), "err_book_time"),     # сенбі
    (datetime(2026, 11, 16, 12, 5), "err_book_time"),     # 10 минутқа еселі емес
    (datetime(2026, 12, 7, 10, 0), "err_book_far"),       # 14 күннен әрі
])
def test_invalid_slots(slot, err):
    with pytest.raises(ql.QueueError) as e:
        ql.validate_booking(slot, MONDAY_10, ql.DEFAULT_SCHEDULE)
    assert e.value.code == err


def test_valid_slot_and_next_slot():
    ql.validate_booking(datetime(2026, 11, 16, 12, 0), MONDAY_10, ql.DEFAULT_SCHEDULE)
    late = datetime(2026, 11, 16, 16, 40)  # 18:40 — жұмыс уақытынан тыс, келесі күн 09:00
    assert ql.next_booking_slot(late, ql.DEFAULT_SCHEDULE) == datetime(2026, 11, 17, 9, 0)


def test_booking_not_in_queue_until_due_then_first(conn):
    live = [repo.create_ticket(conn, student(conn, i), 1, MONDAY_10 + timedelta(minutes=i)) for i in range(3)]
    slot = datetime(2026, 11, 16, 12, 0)
    booked = repo.create_booking(conn, student(conn, 10), 1, slot, MONDAY_10)
    assert booked["booked_at"] == "2026-11-16 12:00:00" and booked["priority"] == 1
    early = MONDAY_10 + timedelta(minutes=30)
    assert repo.people_ahead(conn, booked, early) == 0
    assert repo.waiting_count(conn, 1, "2026-11-16", early) == 3
    assert repo.call_next(conn, op(conn), early)["number"] == live[0]["number"]
    due = slot + timedelta(minutes=1)
    assert repo.people_ahead(conn, live[1], due) == 1      # брондалған алға шықты
    assert repo.people_ahead(conn, booked, due) == 0


def test_booked_called_first_when_due(conn):
    repo.create_ticket(conn, student(conn, 1), 1, MONDAY_10)
    booked = repo.create_booking(conn, student(conn, 2), 1, datetime(2026, 11, 16, 12, 0), MONDAY_10)
    called = repo.call_next(conn, op(conn), datetime(2026, 11, 16, 12, 0))
    assert called["number"] == booked["number"]


def test_slot_taken(conn):
    slot = datetime(2026, 11, 17, 10, 0)
    repo.create_booking(conn, student(conn, 1), 1, slot, MONDAY_10)
    with pytest.raises(ql.QueueError) as e:
        repo.create_booking(conn, student(conn, 2), 1, slot, MONDAY_10)
    assert e.value.code == "err_slot_taken"
    repo.create_booking(conn, student(conn, 3), 2, slot, MONDAY_10)  # басқа қызмет — бос


def test_queue_limit_20_and_bookings_outside(conn):
    assert repo.get_queue_limit(conn) == 20
    for i in range(20):
        repo.create_ticket(conn, student(conn, i), 1 + i % 2, MONDAY_10)
    extra = student(conn, 30)
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, extra, 1, MONDAY_10)
    assert e.value.code == "err_queue_full"
    # брондау шекке кірмейді
    repo.create_booking(conn, extra, 1, datetime(2026, 11, 16, 12, 0), MONDAY_10)
    noon = datetime(2026, 11, 16, 12, 0)
    assert repo.live_waiting(conn, "2026-11-16") == 20
    assert repo.waiting_count(conn, 1, "2026-11-16", noon) == 11


def test_set_queue_limit(conn):
    admin = conn.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    repo.set_queue_limit(conn, admin, "5", MONDAY_10)
    assert repo.get_queue_limit(conn) == 5
    with pytest.raises(ql.QueueError):
        repo.set_queue_limit(conn, admin, "abc", MONDAY_10)


def test_web_booking_flow(client):
    from test_web import login
    login(client, "student")
    html = client.get("/student").get_data(as_text=True)
    assert "Алдын ала уақыт брондау" in html and 'step="600"' in html
    r = client.post("/student/book", data={"service_id": "1", "day": "2026-11-16", "time": "11:00"},
                    follow_redirects=True)
    assert "кемінде 2 сағаттан" in r.get_data(as_text=True)
    r = client.post("/student/book", data={"service_id": "1", "day": "2026-11-17", "time": "10:00"},
                    follow_redirects=True)
    page = r.get_data(as_text=True)
    assert "Уақыт брондалды" in page and "17.11.2026 10:00" in page
    assert "17.11.2026 10:00" in client.get("/student").get_data(as_text=True)
    client.get("/logout")
    login(client, "admin")
    assert "Кезек шегі" in client.get("/admin?tab=schedule").get_data(as_text=True)
    r = client.post("/admin/queue-limit", data={"queue_limit": "15"}, follow_redirects=True)
    assert 'value="15"' in r.get_data(as_text=True)
