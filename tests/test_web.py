"""Веб-қолданбаның тесттері (Flask test client): үш рөл, тіркелу, қауіпсіздік."""
import re

import pytest

from app import i18n
from app.web import create_app

ACCOUNTS = {"student": ("030512501238", "Student2026"),
            "dekanat": ("dekanat1", "Dekanat2026"),
            "admin": ("admin", "Admin2026")}


def login(client, role, username=None, password=None):
    u, p = ACCOUNTS[role]
    return client.post("/login", data={"role": role, "username": username or u,
                                       "password": password or p})


def register_student(client, sid="050720610008", **extra):
    data = {"kind": "student", "full_name": "Дана Серікқызы", "student_id": sid,
            "group_name": "ЭК-23-2", "password": "Parol2026", "password2": "Parol2026"}
    data.update(extra)
    return client.post("/register", data=data)


def take_ticket(client, service_id="1"):
    return client.post("/student/ticket", data={"service_id": service_id})


# ---------------- Ашық беттер және тілдер ----------------
def test_home_shows_three_roles(client):
    html = client.get("/").get_data(as_text=True)
    for word in ("Студент", "Деканат", "Декан орынбасары", "Декан", "Қорқыт Ата"):
        assert word in html


def test_language_switch_to_ru(client):
    html = client.get("/lang/ru?next=/", follow_redirects=True).get_data(as_text=True)
    assert "Электронная очередь деканата" in html and "Заместитель декана" in html


def test_language_switch_unknown_ignored(client):
    html = client.get("/lang/en?next=/", follow_redirects=True).get_data(as_text=True)
    assert "Деканаттың электрондық кезегі" in html


@pytest.mark.parametrize("nxt", ["https://evil.example", "//evil.example", "/\\evil.example"])
def test_open_redirect_blocked(client, nxt):
    assert client.get(f"/lang/ru?next={nxt}").headers["Location"] == "/"


def test_all_translation_keys_present():
    assert all(not missing for missing in i18n.missing_keys().values())


def test_translate_fallback():
    assert i18n.translate("no_such_key", "ru") == "no_such_key"
    assert i18n.translate("app_title", "xx") == i18n.TRANSLATIONS["kk"]["app_title"]


def test_board_page(client):
    r = client.get("/board")
    assert r.status_code == 200 and "Электрондық табло" in r.get_data(as_text=True)


# ---------------- Кіру (үш түрі) ----------------
@pytest.mark.parametrize("role,home", [("student", "/student"), ("dekanat", "/dekanat"),
                                       ("admin", "/admin")])
def test_login_redirects_to_role_home(client, role, home):
    r = login(client, role)
    assert r.status_code == 302 and r.headers["Location"] == home
    assert client.get(home).status_code == 200


def test_login_tabs_on_page(client):
    html = client.get("/login?role=admin").get_data(as_text=True)
    assert "role=student" in html and "role=dekanat" in html and "role=deputy" in html
    assert 'class="active" href="/login?role=admin"' in html


def test_wrong_password(client):
    html = login(client, "student", password="bad").get_data(as_text=True)
    assert "Логин (ЖСН) немесе құпиясөз қате" in html


def test_login_works_from_any_tab(client):
    """Декан «Студент» не «Деканат» қойындысынан кірсе де, өз панеліне өтеді (бұрын қате шығатын)."""
    r = login(client, "student", *ACCOUNTS["admin"])
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin")


def test_login_rate_limit(tmp_path, clock):
    app = create_app({"DATABASE": str(tmp_path / "l.db"), "SECRET_KEY": "x", "TESTING": True,
                      "WTF_CSRF_DISABLED": True, "NOW": clock, "LOGIN_LIMIT": 3})
    c = app.test_client()
    for _ in range(3):
        login(c, "admin", password="bad")
    assert login(c, "admin").status_code == 429


def test_logout(client):
    login(client, "student")
    client.post("/logout")
    assert client.get("/student").status_code == 302


# ---------------- Рөлдерге қол жеткізу ----------------
@pytest.mark.parametrize("url", ["/student", "/dekanat", "/admin", "/profile"])
def test_pages_require_login(client, url):
    r = client.get(url)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


@pytest.mark.parametrize("role,url,allowed", [
    ("student", "/dekanat", False), ("student", "/admin", False),
    ("dekanat", "/admin", False), ("dekanat", "/student", False),
    ("admin", "/dekanat", True), ("admin", "/admin", True),
])
def test_role_access(client, role, url, allowed):
    login(client, role)
    r = client.get(url)
    assert (r.status_code == 200) is allowed


def test_student_cannot_post_admin_actions(client, app):
    login(client, "student")
    client.post("/admin/users/1/block")
    conn = app.extensions["db"]
    assert conn.execute("SELECT is_active FROM users WHERE id=1").fetchone()[0] == 1


# ---------------- Тіркелу ----------------
def test_register_student_and_login(client):
    r = register_student(client)
    assert r.status_code == 302 and "role=student" in r.headers["Location"]
    r = client.post("/login", data={"role": "student", "username": "050720610008",
                                    "password": "Parol2026"})
    assert r.headers["Location"] == "/student"


def test_register_errors_shown(client):
    html = register_student(client, sid="12", password2="other").get_data(as_text=True)
    assert "ЖСН қате" in html and "сәйкес келмейді" in html


def test_register_duplicate(client):
    register_student(client)
    html = register_student(client).get_data(as_text=True)
    assert "бұрыннан тіркелген" in html


def test_register_staff_pending_until_admin_approves(client, app):
    client.post("/register", data={"kind": "dekanat", "full_name": "Жанар Сейітова",
                                   "username": "jseitova", "password": "Parol2026",
                                   "password2": "Parol2026"})
    html = client.post("/login", data={"role": "dekanat", "username": "jseitova",
                                       "password": "Parol2026"}).get_data(as_text=True)
    assert "расталмаған" in html
    new_id = app.extensions["db"].execute(
        "SELECT id FROM users WHERE username='jseitova'").fetchone()[0]
    login(client, "admin")
    assert "jseitova" in client.get("/admin").get_data(as_text=True)
    client.post(f"/admin/users/{new_id}/activate")
    client.post("/logout")
    r = client.post("/login", data={"role": "dekanat", "username": "jseitova",
                                    "password": "Parol2026"})
    assert r.headers["Location"] == "/dekanat"


def test_admin_registration_waits_for_admin_approval(client, app):
    """Әкімші болып тіркелуге болады, бірақ қазіргі әкімші растамайынша кіре алмайды."""
    html = client.get("/register?kind=admin").get_data(as_text=True)
    assert "тек қазіргі администратор растай алады" in html
    client.post("/register", data={"kind": "admin", "full_name": "Жаңа Декан",
                                   "username": "newdean", "password": "Parol2026",
                                   "password2": "Parol2026"})
    conn = app.extensions["db"]
    row = conn.execute("SELECT id, role, is_active FROM users WHERE username='newdean'").fetchone()
    assert row["role"] == "admin" and row["is_active"] == 0
    html = client.post("/login", data={"role": "admin", "username": "newdean",
                                       "password": "Parol2026"}).get_data(as_text=True)
    assert "расталмаған" in html
    # орынбасар әкімші өтінімін растай алмайды
    client.post("/login", data={"role": "deputy", "username": "zamdekan", "password": "Deputy2026"})
    client.post(f"/admin/users/{row['id']}/activate")
    assert conn.execute("SELECT is_active FROM users WHERE id=?", (row["id"],)).fetchone()[0] == 0
    client.post("/logout")
    # әкімші растайды — енді кіре алады
    login(client, "admin")
    client.post(f"/admin/users/{row['id']}/activate")
    client.post("/logout")
    r = client.post("/login", data={"role": "admin", "username": "newdean", "password": "Parol2026"})
    assert r.headers["Location"] == "/admin"


def test_register_page_has_all_roles(client):
    html = client.get("/register").get_data(as_text=True)
    for r in ("kind=student", "kind=dekanat", "kind=deputy", "kind=admin"):
        assert r in html


# ---------------- Студент ----------------
def test_student_takes_ticket(client):
    login(client, "student")
    r = take_ticket(client)
    assert r.status_code == 302 and "/ticket/" in r.headers["Location"]
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "A-001" in page and "Талоннан бас тарту" in page
    cabinet = client.get("/student").get_data(as_text=True)
    assert "A-001" in cabinet


def test_ticket_api_hides_personal_data(client):
    login(client, "student")
    token = take_ticket(client).headers["Location"].rsplit("/", 1)[-1]
    data = client.get(f"/api/ticket/{token}").get_json()
    assert data["number"] == "A-001" and data["status"] == "waiting"
    assert "full_name" not in data and "student_id" not in data


def test_student_cancel(client):
    login(client, "student")
    take_ticket(client)
    ticket_id = re.search(r"/student/ticket/(\d+)/cancel",
                          client.get("/student").get_data(as_text=True)).group(1)
    html = client.post(f"/student/ticket/{ticket_id}/cancel", follow_redirects=True).get_data(as_text=True)
    assert "Талоннан бас тартылды" in html


def test_student_cannot_cancel_foreign_ticket(client, app):
    login(client, "student")
    take_ticket(client)
    client.post("/logout")
    register_student(client)
    client.post("/login", data={"role": "student", "username": "050720610008", "password": "Parol2026"})
    client.post("/student/ticket/1/cancel")
    status = app.extensions["db"].execute("SELECT status FROM tickets WHERE id=1").fetchone()[0]
    assert status == "waiting"


def test_closed_on_weekend(client, clock):
    clock.value = clock.value.replace(day=14)  # сенбі
    login(client, "student")
    html = take_ticket(client)
    html = client.get("/student").get_data(as_text=True)
    assert "Деканат қазір жұмыс істемейді" in html


def test_unknown_ticket_404(client):
    assert client.get("/ticket/nope").status_code == 404
    assert client.get("/api/ticket/nope").status_code == 404


# ---------------- Деканат ----------------
def test_full_dekanat_flow(client, clock):
    login(client, "student")
    token = take_ticket(client).headers["Location"].rsplit("/", 1)[-1]
    client.post("/logout")
    login(client, "dekanat")
    clock.advance(3)
    assert "A-001" in client.post("/dekanat/next", follow_redirects=True).get_data(as_text=True)
    data = client.get(f"/api/ticket/{token}").get_json()
    assert data["status"] == "called" and data["window"] == 2
    assert client.get("/api/board").get_json()["called"][0]["number"] == "A-001"
    ticket_id = re.search(r"/dekanat/ticket/(\d+)/done",
                          client.get("/dekanat").get_data(as_text=True)).group(1)
    clock.advance(5)
    client.post(f"/dekanat/ticket/{ticket_id}/done")
    assert client.get(f"/api/ticket/{token}").get_json()["status"] == "done"


def test_dekanat_bad_action_404(client):
    login(client, "dekanat")
    assert client.post("/dekanat/ticket/1/hack").status_code == 404


def test_logout_sets_off_duty(client, app):
    login(client, "dekanat")
    conn = app.extensions["db"]
    q = "SELECT on_duty FROM users WHERE username='dekanat1'"
    assert conn.execute(q).fetchone()[0] == 1
    client.post("/logout")
    assert conn.execute(q).fetchone()[0] == 0


# ---------------- Әкімші ----------------
@pytest.mark.parametrize("tab", ["users", "services", "tickets", "audit", "bogus"])
def test_admin_tabs_render(client, tab):
    login(client, "admin")
    assert client.get(f"/admin?tab={tab}").status_code == 200


def test_admin_blocks_student(client, app):
    login(client, "admin")
    sid = app.extensions["db"].execute("SELECT id FROM users WHERE username='030512501238'").fetchone()[0]
    client.post(f"/admin/users/{sid}/block")
    client.post("/logout")
    assert "бұғатталған" in login(client, "student").get_data(as_text=True)


def test_blocked_user_session_is_dropped(client, app):
    login(client, "student")
    app.extensions["db"].execute("UPDATE users SET is_active=0 WHERE username='030512501238'")
    assert client.get("/student").status_code == 302


def test_admin_cannot_block_self(client):
    login(client, "admin")
    html = client.post("/admin/users/1/block", follow_redirects=True).get_data(as_text=True)
    assert "Өз аккаунтыңызға" in html


def test_admin_creates_user(client, app):
    login(client, "admin")
    client.post("/admin/users/new", data={"role": "dekanat", "full_name": "Жаңа Әдіскер",
                                          "username": "newone", "password": "Parol2026",
                                          "window_no": "4"})
    row = app.extensions["db"].execute(
        "SELECT role, window_no, is_active FROM users WHERE username='newone'").fetchone()
    assert tuple(row) == ("dekanat", 4, 1)


def test_admin_fixes_ticket_and_audit(client, app):
    login(client, "student")
    take_ticket(client)
    client.post("/logout")
    login(client, "admin")
    client.post("/admin/tickets/1/status", data={"status": "cancelled"})
    assert app.extensions["db"].execute("SELECT status FROM tickets WHERE id=1").fetchone()[0] == "cancelled"
    assert "ticket_status" in client.get("/admin?tab=audit").get_data(as_text=True)


def test_admin_adds_service(client):
    login(client, "admin")
    client.post("/admin/services/save", data={"code": "G", "name_kk": "Стипендия",
                                              "name_ru": "Стипендия", "avg_minutes": "5",
                                              "is_active": "1"})
    html = client.get("/").get_data(as_text=True)
    assert "Стипендия" in html and "G. Стипендия" not in html  # әріп-код көрсетілмейді


# ---------------- Профиль ----------------
def test_profile_change_password(client):
    login(client, "student")
    assert "030512501238" in client.get("/profile").get_data(as_text=True)
    html = client.post("/profile", data={"old_password": "Student2026", "password": "NewPass1",
                                         "password2": "NewPass1"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Құпиясөз өзгертілді" in html
    client.post("/logout")
    assert login(client, "student", password="NewPass1").headers["Location"] == "/student"


# ---------------- Қауіпсіздік ----------------
def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_xss_is_escaped(client):
    html = register_student(client, full_name="<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_csrf_protection(tmp_path, clock):
    app = create_app({"DATABASE": str(tmp_path / "c.db"), "SECRET_KEY": "x", "TESTING": True,
                      "NOW": clock})
    c = app.test_client()
    r = login(c, "admin")  # csrf_token жоқ
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    with c.session_transaction() as s:
        assert "user_id" not in s


def test_ticket_rate_limit(tmp_path, clock):
    app = create_app({"DATABASE": str(tmp_path / "r.db"), "SECRET_KEY": "x", "TESTING": True,
                      "WTF_CSRF_DISABLED": True, "CHECK_HOURS": True, "NOW": clock,
                      "RATE_LIMIT": 2})
    c = app.test_client()
    login(c, "student")
    take_ticket(c, "1")
    take_ticket(c, "2")
    html = c.post("/student/ticket", data={"service_id": "3"},
                  follow_redirects=True).get_data(as_text=True)
    assert "Тым көп сұрау" in html


# ---------------- Басты бет: университет туралы ----------------
def test_home_has_university_sections(client):
    html = client.get("/").get_data(as_text=True)
    for anchor in ('id="about"', 'id="history"', 'id="building5"',
                   'id="partners"', 'id="contacts"'):
        assert anchor in html
    assert "№5 оқу корпусы" in html and "Абай даңғылы, 66А" in html
    assert "University of Łódź" in html and "26 елдің" in html
    assert "ksu@korkyt.kz" in html


def test_home_in_russian(client):
    html = client.get("/lang/ru?next=/", follow_redirects=True).get_data(as_text=True)
    assert "Учебный корпус №5" in html and "Партнёры университета" in html
    assert "из 26 стран" in html


def test_home_live_queue_counts(client):
    login(client, "student")
    take_ticket(client)
    client.post("/logout")
    html = client.get("/").get_data(as_text=True)
    assert re.search(r"<b>1</b><span>адам күтуде", html)


def test_home_external_links_are_safe(client):
    html = client.get("/").get_data(as_text=True)
    for m in re.finditer(r'<a [^>]*target="_blank"[^>]*>', html):
        assert 'rel="noopener noreferrer"' in m.group(0)


# ---------------- Бір мезеттегі сұраулар (регрессия) ----------------
def test_concurrent_requests_do_not_crash(app):
    """Бұрын бір SQLite қосылымы ағындар арасында ортақ болып, бет 500 қатесімен құлайтын."""
    from concurrent.futures import ThreadPoolExecutor

    def hit(i):
        with app.test_client() as c:
            url = ("/", "/board", "/api/board", "/login")[i % 4]
            return c.get(url).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(hit, range(80)))
    assert set(codes) == {200}


# ---------------- Телефон: QR-код, желі режимі, мобильді мәзір ----------------
def test_qr_code_svg(client):
    r = client.get("/qr.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    assert r.get_data(as_text=True).lstrip().startswith("<svg")


def test_qr_uses_public_url(tmp_path, clock):
    app = create_app({"DATABASE": str(tmp_path / "q.db"), "SECRET_KEY": "x", "TESTING": True,
                      "NOW": clock, "PUBLIC_URL": "http://192.168.1.50:5000/"})
    html = app.test_client().get("/board").get_data(as_text=True)
    assert "http://192.168.1.50:5000/" in html


def test_qr_ignores_query_params(client):
    """QR тек сайттың өз мекенжайын кодтайды — сырттан мәтін қабылданбайды."""
    a = client.get("/qr.svg").get_data()
    b = client.get("/qr.svg?u=https://evil.example").get_data()
    assert a == b


def test_mobile_menu_and_viewport(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="nav-toggle"' in html and 'aria-controls="main-nav"' in html
    assert 'name="viewport"' in html and 'name="theme-color"' in html


def test_tables_have_mobile_labels(client):
    login(client, "student")
    take_ticket(client)
    client.post("/logout")
    login(client, "admin")
    html = client.get("/admin?tab=tickets").get_data(as_text=True)
    assert 'class="table table-cards"' in html and 'data-label="Талон"' in html


def test_local_ips_filters_loopback():
    from app.web import local_ips
    for ip in local_ips():
        assert not ip.startswith(("127.", "169.254.", "0."))
        assert ip.count(".") == 3
