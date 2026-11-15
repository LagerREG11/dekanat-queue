"""Веб: декан орынбасары, жұмыс кестесі, қызметкер үзілісі, көмекші-чат."""
from datetime import UTC

from app.web import create_app

DEPUTY = ("zamdekan", "Deputy2026")


def login(client, role, username, password):
    return client.post("/login", data={"role": role, "username": username, "password": password})


def login_deputy(client):
    return login(client, "deputy", *DEPUTY)


def test_deputy_login_and_access(client):
    assert login_deputy(client).headers["Location"] == "/admin"
    assert client.get("/admin").status_code == 200
    assert client.get("/dekanat").status_code == 200


def test_deputy_cannot_create_dean(client, app):
    login_deputy(client)
    client.post("/admin/users/new", data={"role": "admin", "full_name": "Жаңа Декан",
                                          "username": "newdean", "password": "Parol2026"})
    assert app.extensions["db"].execute("SELECT 1 FROM users WHERE username='newdean'").fetchone() is None
    assert '<option value="admin"' not in client.get("/admin").get_data(as_text=True)


def test_schedule_tab_and_save(client):
    login_deputy(client)
    assert 'name="breaks"' not in client.get("/admin?tab=schedule").get_data(as_text=True)
    r = client.post("/admin/schedule", data={"open_at": "08:00", "close_at": "17:00",
                                             "lunch_from": "12:00", "lunch_to": "13:00",
                                             "breaks": "10:00-10:10", "workdays": ["0", "1", "2", "3", "4"]},
                    follow_redirects=True)
    assert "Сақталды" in r.get_data(as_text=True)
    home = client.get("/").get_data(as_text=True)
    assert "08:00–17:00" in home and "12:00–13:00" in home
    assert "10:00–10:10" not in home                                 # қысқа үзіліс қабылданбайды


def test_schedule_validation_error(client):
    login_deputy(client)
    r = client.post("/admin/schedule", data={"open_at": "18:00", "close_at": "09:00", "workdays": ["0"]},
                    follow_redirects=True)
    assert "ерте болуы керек" in r.get_data(as_text=True)


def test_student_cannot_change_schedule(client):
    login(client, "student", "030512501238", "Student2026")
    assert client.post("/admin/schedule", data={"open_at": "08:00"}).status_code == 302


def test_home_shows_lunch_without_short_breaks_and_institutes(client):
    html = client.get("/").get_data(as_text=True)
    assert "13:00–14:00" in html
    assert "11:00–11:15" not in html and "16:00–16:15" not in html
    assert "80 000" not in html and "Гуманитарлық-педагогикалық институт" not in html


def test_staff_break_flow(client):
    login(client, "dekanat", "dekanat1", "Dekanat2026")
    html = client.post("/dekanat/break", follow_redirects=True).get_data(as_text=True)
    assert "Үзіліс басталды" in html and "Жұмысқа оралу" in html
    assert client.get("/api/board").get_json()["windows"] == [{"window_no": 2, "on_break": True}]
    html = client.post("/dekanat/next", follow_redirects=True).get_data(as_text=True)
    assert "Сіз үзілістесіз" in html
    client.post("/dekanat/break")
    assert client.get("/api/board").get_json()["windows"][0]["on_break"] is False


def test_chat_api(client):
    r = client.post("/api/chat", json={"message": "жұмыс уақыты"})
    data = r.get_json()
    assert r.status_code == 200 and "09:00–18:00" in data["reply"] and data["suggestions"]


def test_chat_api_russian_and_queue(client):
    login(client, "student", "030512501238", "Student2026")
    client.post("/student/ticket", data={"service_id": "1"})
    client.get("/lang/ru?next=/")
    data = client.post("/api/chat", json={"message": "Сколько человек в очереди?"}).get_json()
    assert "1 чел." in data["reply"]


def test_chat_requires_csrf(tmp_path, clock):
    app = create_app({"DATABASE": str(tmp_path / "c2.db"), "SECRET_KEY": "x", "TESTING": True, "NOW": clock})
    c = app.test_client()
    assert c.post("/api/chat", json={"message": "сәлем"}).status_code == 400
    c.get("/")
    with c.session_transaction() as s:
        token = s["csrf"]
    r = c.post("/api/chat", json={"message": "сәлем"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and "Сәлеметсіз бе" in r.get_json()["reply"]


def test_chat_rate_limit(client):
    codes = [client.post("/api/chat", json={"message": "сәлем"}).status_code for _ in range(32)]
    assert 429 in codes


def test_chat_widget_on_every_page(client):
    for url in ("/", "/board", "/login"):
        assert 'id="chat"' in client.get(url).get_data(as_text=True)


def test_no_ratings_or_country_chips(client):
    html = client.get("/").get_data(as_text=True)
    assert "QS Asia" not in html and "Рейтинг" not in html and "country-chips" not in html


# ---------------- Талон бірден көрінеді (тірі жаңарту) ----------------
def test_new_ticket_visible_to_dean_immediately(app):
    """Студент талон алған сәтте декан/деканат панелінің API-і оны қайтарады."""
    student, dean = app.test_client(), app.test_client()
    login(dean, "admin", "admin", "Admin2026")
    assert dean.get("/api/staff/queue").get_json()["waiting"] == []
    login(student, "student", "030512501238", "Student2026")
    r = student.post("/student/ticket", data={"service_id": "1"})
    assert "/ticket/" in r.headers["Location"]
    data = dean.get("/api/staff/queue").get_json()
    assert data["waiting"][0]["number"] == "A-001"
    assert data["waiting"][0]["full_name"] == "Айгерім Сәрсенова"
    assert data["stats"]["waiting"] == 1
    # студент кабинетінде де бірден бар
    assert "A-001" in student.get("/student").get_data(as_text=True)


def test_manage_changes_signature(app):
    student, dean = app.test_client(), app.test_client()
    login(dean, "admin", "admin", "Admin2026")
    before = dean.get("/api/manage/changes").get_json()
    login(student, "student", "030512501238", "Student2026")
    student.post("/student/ticket", data={"service_id": "2"})
    after = dean.get("/api/manage/changes").get_json()
    assert after["signature"] != before["signature"] and after["tickets"] == before["tickets"] + 1


def test_student_tickets_signature_changes_when_called(app):
    student, staff = app.test_client(), app.test_client()
    login(student, "student", "030512501238", "Student2026")
    student.post("/student/ticket", data={"service_id": "1"})
    sig1 = student.get("/api/student/tickets").get_json()["signature"]
    login(staff, "dekanat", "dekanat1", "Dekanat2026")
    staff.post("/dekanat/next")
    sig2 = student.get("/api/student/tickets").get_json()["signature"]
    assert sig1 != sig2


def test_live_apis_require_roles(client):
    assert client.get("/api/staff/queue").status_code == 302
    assert client.get("/api/manage/changes").status_code == 302
    assert client.get("/api/student/tickets").status_code == 302
    login(client, "student", "030512501238", "Student2026")
    assert client.get("/api/staff/queue").status_code == 302


def test_operator_page_has_live_hooks(client):
    login(client, "dekanat", "dekanat1", "Dekanat2026")
    html = client.get("/dekanat").get_data(as_text=True)
    assert 'id="waiting-body"' in html and 'id="new-ticket-alert"' in html and "/api/staff/queue" in html


def test_local_clock_uses_qyzylorda_time():
    """Хостинг UTC-пен жұмыс істесе де, деканат уақыты UTC+5 болуы керек."""
    from datetime import datetime, timedelta

    from app.web import _local_clock
    local = _local_clock("Asia/Qyzylorda")()
    utc = datetime.now(UTC).replace(tzinfo=None)
    assert abs((local - utc) - timedelta(hours=5)) < timedelta(minutes=1)
    assert abs(_local_clock("No/Such_Zone")() - datetime.now()) < timedelta(minutes=1)


def test_password_eye_labels_on_login_and_register(client):
    """«Көз» батырмасы (app.js) үшін аудармалар әр бетте бар."""
    for url in ("/login", "/register"):
        html = client.get(url).get_data(as_text=True)
        assert 'data-pw-show="Құпиясөзді көрсету"' in html and 'data-pw-hide="Құпиясөзді жасыру"' in html
        assert 'type="password"' in html


def test_student_cabinet_has_no_priority_checkbox(client):
    """Басым кезек белгісі алынып тасталды (тапсырыс берушінің талабы)."""
    from conftest import make_iin
    sid = make_iin(700)
    client.post("/register", data={"kind": "student", "full_name": "Айгүл Сәрсенова", "student_id": sid,
                                   "group_name": "ИС-24-1", "password": "Aigul#2026", "password2": "Aigul#2026"})
    client.post("/login", data={"username": sid, "password": "Aigul#2026"})
    html = client.get("/student").get_data(as_text=True)
    assert 'name="priority"' not in html
    client.post("/student/ticket", data={"service_id": "1", "priority": "1"})
    assert client.application.extensions["db"].execute(
        "SELECT priority FROM tickets ORDER BY id DESC LIMIT 1").fetchone()[0] == 0


def test_no_login_hint_and_no_course_project_note(client):
    """Кіру бетіндегі ескерту мен төменгі бөліктегі «Курстық жоба · 5-нұсқа» алынып тасталды."""
    html = client.get("/login").get_data(as_text=True)
    assert "таңдаған логиніңізді" not in html and "Курстық жоба" not in html
