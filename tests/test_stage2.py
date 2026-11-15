"""2-кезең: талон беру уақыты (08:45–18:00), мерекелер және ерекше күндер, күнтізбе,
хабарландырулар, ЖСН, құпиясөз беріктігі, профиль (телефон, жыныс, e-mail, сурет)."""
import io
import re
from datetime import date, datetime, time

import pytest
from conftest import MONDAY_10

from app import chatbot
from app import db as repo
from app import service as ql
from app.web import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def D(h, m=0, day=16):
    """16.11.2026 — дүйсенбі."""
    return datetime(2026, 11, day, h, m)


# ---------------- ЖСН ----------------
@pytest.mark.parametrize("iin,ok", [
    ("030512501238", True),
    ("030512501239", False),   # бақылау цифры қате
    ("031332501238", False),   # 13-ші ай жоқ
    ("030512901238", False),   # 7-ші цифр (ғасыр) 1–6 болуы керек
    ("03051250123", False),    # 11 цифр
    ("0305125012ab", False),
    ("", False), (None, False),
])
def test_iin(iin, ok):
    assert ql.is_valid_iin(iin) is ok


# ---------------- Құпиясөз беріктігі ----------------
@pytest.mark.parametrize("pw,level", [
    ("aigerim2005", "weak"),       # аты + туған жылы
    ("AIGERIM2005", "weak"),       # тек бас әріп
    ("Aigerim", "weak"),           # қысқа
    ("Aigerim2005", "medium"),     # кіші + бас әріп + цифр
    ("aigerim#2005", "strong"),    # тыныс белгісі + әріп + цифр
    ("Aigerim.2005", "strong"),
    ("Айгерім!2005", "strong"),    # кирилл әріптері де есептеледі
])
def test_password_strength(pw, level):
    assert ql.password_strength(pw) == level


def test_password_length_limits():
    assert ql.validate_password("Ab1" + "x" * 13) == []                       # 16 таңба
    assert ql.validate_password("Ab1" + "x" * 14) == ["err_password_length"]  # 17 таңба
    assert ql.validate_password("aigerim2005") == ["err_password_weak"]


# ---------------- Талон беру уақыты ----------------
@pytest.mark.parametrize("moment,ok", [
    (D(8, 44), False), (D(8, 45), True), (D(8, 59), True), (D(10), True),
    (D(13, 30), False),            # түскі үзіліс
    (D(11, 5), True),              # қысқа үзілістер алынып тасталды
    (D(17, 59), True), (D(18, 0), False), (D(21), False),
    (D(10, day=21), False),        # сенбі
])
def test_booking_window(moment, ok):
    assert ql.can_take_ticket(moment) is ok


def test_next_booking_time():
    assert ql.next_booking_time(D(19)) == D(8, 45, day=17)               # кеш -> ертең 08:45
    assert ql.next_booking_time(D(7)) == D(8, 45)                        # таң -> бүгін 08:45
    assert ql.next_booking_time(D(13, 20)) == D(14)                      # түскі үзіліс -> 14:00
    assert ql.next_booking_time(datetime(2026, 11, 20, 18, 30)) == D(8, 45, day=23)  # жұма -> дүйсенбі
    assert ql.next_booking_time(D(10)) == D(10)                          # қазір беріліп жатыр


def test_holiday_and_short_day():
    dec16 = date(2026, 12, 16)  # Тәуелсіздік күні (сәрсенбі)
    plan = ql.day_plan(dec16)
    assert plan.kind == "holiday" and plan.holiday[0] == "Тәуелсіздік күні"
    assert not ql.can_take_ticket(datetime(2026, 12, 16, 10))
    o = ql.build_override("2026-11-17", "short", "09:00", "13:00", "Декан жиналыста")
    ov = {o.day: o}
    assert ql.day_plan(o.day, overrides=ov).kind == "short"
    assert ql.can_take_ticket(D(12, 50, day=17), overrides=ov)
    assert not ql.can_take_ticket(D(13, 30, day=17), overrides=ov)
    assert ql.next_booking_time(D(14, day=17), overrides=ov) == D(8, 45, day=18)
    off = ql.build_override("2026-11-18", "holiday", note="Құрбан айт")
    assert ql.day_plan(off.day, overrides={off.day: off}).kind == "holiday"


@pytest.mark.parametrize("args,code", [
    (("2026-13-01", "short", "09:00", "13:00"), "err_date"),
    (("2026-11-17", "party"), "err_day_kind"),
    (("2026-11-17", "short", "13:00", "09:00"), "err_hours_order"),
    (("2026-11-17", "holiday", "", "", "x" * 201), "err_note_long"),
])
def test_override_validation(args, code):
    with pytest.raises(ql.QueueError) as e:
        ql.build_override(*args)
    assert e.value.code == code


def test_month_calendar_states():
    weeks = ql.month_calendar(2026, 11, date(2026, 11, 16))
    cells = {c["day"]: c for w in weeks for c in w if c}
    assert len(cells) == 30 and weeks[0][:6] == [None] * 6   # 1 қараша — жексенбі
    assert cells[13]["when"] == "past" and cells[16]["when"] == "today" and cells[17]["when"] == "future"
    assert cells[21]["plan"].kind == "weekend" and cells[17]["plan"].kind == "work"


# ---------------- Хабарландыру, профиль ----------------
def test_announcement_validation():
    a = ql.build_announcement("  13:00-ден кейін декан болмайды  ", "", "", date(2026, 11, 16))
    assert a.text.startswith("13:00") and a.start == a.end == date(2026, 11, 16)
    for args, code in [(("abc", "", ""), "err_announcement"),
                       (("Мәтін бар", "2026-11-20", "2026-11-19"), "err_date_order"),
                       (("Мәтін бар", "20.11.2026", ""), "err_date")]:
        with pytest.raises(ql.QueueError) as e:
            ql.build_announcement(*args, date(2026, 11, 16))
        assert e.value.code == code


@pytest.mark.parametrize("raw,clean", [
    ("8 701 234 56 78", "+7 701 234 56 78"), ("+7(701)234-56-78", "+7 701 234 56 78"), ("", ""),
])
def test_phone_normalized(raw, clean):
    assert ql.normalize_phone(raw) == clean


def test_profile_validation_errors():
    for args, code in [(("123", "", ""), "err_phone"), (("", "x", ""), "err_gender"),
                       (("", "", "not-an-email"), "err_email")]:
        with pytest.raises(ql.QueueError) as e:
            ql.validate_profile(*args)
        assert e.value.code == code
    assert ql.validate_profile("", "female", "Dana@Mail.KZ")["email"] == "dana@mail.kz"


def test_detect_image_type():
    assert ql.detect_image_type(PNG) == "png" and ql.detect_image_type(JPG) == "jpg"
    assert ql.detect_image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    with pytest.raises(ql.QueueError):
        ql.detect_image_type(b"<svg onload=alert(1)>")


def test_chatbot_polite_fallback():
    reply = chatbot.answer("ертең ауа райы қандай?", "kk", {"contacts": {"phone": "1"}})["reply"]
    assert "түсінбедім" not in reply and "деканатқа барғанда" in reply


# ---------------- Дерекқор ----------------
def test_overrides_and_announcements_db(conn):
    admin = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    staff = conn.execute("SELECT id FROM users WHERE role='student'").fetchone()[0]
    o = ql.build_override("2026-11-17", "short", "09:00", "13:00", "Жиналыс")
    repo.save_override(conn, admin, o, MONDAY_10)
    assert repo.get_overrides(conn)[o.day].close_at == time(13, 0)
    with pytest.raises(ql.QueueError):
        repo.save_override(conn, staff, o, MONDAY_10)          # студентке рұқсат жоқ
    repo.delete_override(conn, admin, "2026-11-17", MONDAY_10)
    assert repo.get_overrides(conn) == {}

    a = ql.build_announcement("Ертең қабылдау 13:00-ге дейін", "2026-11-16", "2026-11-17", MONDAY_10.date())
    aid = repo.add_announcement(conn, admin, a, MONDAY_10)
    assert len(repo.active_announcements(conn, MONDAY_10)) == 1
    assert repo.active_announcements(conn, datetime(2026, 11, 18, 9)) == []
    repo.delete_announcement(conn, admin, aid, MONDAY_10)
    assert repo.list_announcements(conn, MONDAY_10) == []


def test_ticket_refused_on_short_day_afternoon(conn):
    admin = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    repo.save_override(conn, admin, ql.build_override("2026-11-16", "short", "09:00", "13:00"), MONDAY_10)
    student = repo.get_user(conn, conn.execute("SELECT id FROM users WHERE role='student'").fetchone()[0])
    assert repo.create_ticket(conn, student, 1, D(12)) is not None
    with pytest.raises(ql.QueueError) as e:
        repo.create_ticket(conn, student, 2, D(14, 30))
    assert e.value.code == "err_closed"


def test_old_database_gets_new_service_and_profile_columns(tmp_path):
    """Ескі дерекқор (профиль бағандарынсыз, бұрынғы қызмет уақыттарымен) жоғалтусыз жаңарады."""
    path = tmp_path / "old.db"
    old_schema = re.sub(r",\n    phone .*?-- instance/avatars[^\n]*", "", repo.SCHEMA, flags=re.DOTALL)
    assert "avatar" not in old_schema.split("CREATE TABLE IF NOT EXISTS day_overrides")[0]
    old = repo.connect(path)
    old.executescript(old_schema)
    old.executemany("INSERT INTO services (code, name_kk, name_ru, avg_minutes) VALUES (?,?,?,?)",
                    [("A", "Анықтама алу", "Справка", 4), ("B", "Өтініш тапсыру", "Заявление", 6)])
    old.close()
    conn = repo.connect(path)
    repo.init_db(conn)
    repo.seed(conn, MONDAY_10)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"phone", "gender", "email", "avatar"} <= cols
    assert dict(conn.execute("SELECT code, avg_minutes FROM services").fetchall()) == {"A": 3, "B": 5, "F": 1}
    repo.seed(conn, MONDAY_10)  # екінші рет — өзгеріс жоқ
    assert conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 3
    conn.close()


def test_force_set_password(conn):
    repo.force_set_password(conn, "Admin", "NewDean#2026", MONDAY_10)
    user, err = repo.authenticate(conn, "admin", "NewDean#2026")
    assert err is None and user["role"] == "admin"
    with pytest.raises(ql.QueueError):
        repo.force_set_password(conn, "nobody", "NewDean#2026", MONDAY_10)
    with pytest.raises(ql.QueueError):
        repo.force_set_password(conn, "admin", "weakpass1", MONDAY_10)


# ---------------- Веб ----------------
def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def test_student_cannot_take_ticket_after_18(client, clock):
    clock.value = D(18, 30)
    login(client, "030512501238", "Student2026")
    html = client.get("/student").get_data(as_text=True)
    assert "Талон ертең 08:45-ден бастап беріледі" in html
    r = client.post("/student/ticket", data={"service_id": "1"}, follow_redirects=True)
    assert "талон беру мүмкін емес" in r.get_data(as_text=True)
    clock.value = D(8, 45, day=17)
    r = client.post("/student/ticket", data={"service_id": "1"})
    assert r.status_code == 302 and "/ticket/" in r.headers["Location"]


def test_home_calendar_and_service_minutes(client):
    html = client.get("/").get_data(as_text=True)
    assert "Қараша 2026" in html and 'class="cal-today kind-work"' in html
    assert "cal-past" in html and "Демалыс" in html
    assert "қабылдау ~1 мин" in html and "Өтінішке қол қою" in html
    assert "8 777 777 77 77" in html and "tel:+77777777777" in html and "11 700+" in html
    assert "img/building5.webp" in html


def test_manager_announcement_and_short_day_on_all_pages(client):
    login(client, "admin", "Admin2026")
    client.post("/admin/announcements/new", data={"text": "13:00-ден кейін декан жиналыста болады."})
    client.post("/admin/days/save", data={"day": "2026-11-16", "kind": "short", "open_at": "09:00",
                                          "close_at": "13:00", "note": "Декан іште болмайды"})
    client.post("/logout")
    html = client.get("/").get_data(as_text=True)
    assert "13:00-ден кейін декан жиналыста болады." in html
    assert "бүгін деканат тек 09:00–13:00 аралығында" in html and "Декан іште болмайды" in html
    assert 'class="cal-today kind-short"' in html
    assert "декан жиналыста" in client.get("/board").get_data(as_text=True)


def test_student_cannot_post_announcement(client):
    login(client, "030512501238", "Student2026")
    client.post("/admin/announcements/new", data={"text": "Рұқсатсыз хабарландыру"})
    client.post("/logout")
    assert "Рұқсатсыз хабарландыру" not in client.get("/").get_data(as_text=True)


def test_register_with_iin_and_weak_password(client):
    data = {"kind": "student", "full_name": "Дана Серікқызы", "student_id": "050720610008",
            "group_name": "ЭК-23-2", "password": "dana2005", "password2": "dana2005"}
    assert "Құпиясөз әлсіз" in client.post("/register", data=data).get_data(as_text=True)
    data.update(password="Dana#2005", password2="Dana#2005")
    assert client.post("/register", data=data).status_code == 302
    assert login(client, "050720610008", "Dana#2005").headers["Location"].endswith("/student")


def test_profile_info_saved(client):
    login(client, "030512501238", "Student2026")
    client.post("/profile", data={"action": "info", "phone": "8 701 234 56 78",
                                  "gender": "female", "email": "aigerim@mail.kz"})
    html = client.get("/profile").get_data(as_text=True)
    assert "+7 701 234 56 78" in html and "aigerim@mail.kz" in html and "Әйел" in html
    html = client.post("/profile", data={"action": "info", "phone": "123"}).get_data(as_text=True)
    assert "Телефон нөмірі қате" in html



def test_admin_edits_full_name_others_cannot(client):
    """Администратор мен студент профильде аты-жөнін өзгертеді; студент тобын да толтырады."""
    login(client, "admin", "Admin2026")
    assert 'name="full_name"' in client.get("/profile").get_data(as_text=True)
    client.post("/profile", data={"action": "info", "full_name": "Сейітов Нұрлан Асқарұлы",
                                  "phone": "8 777 123 45 67", "gender": "male", "email": "admin@korkyt.kz"})
    html = client.get("/profile").get_data(as_text=True)
    assert "Сейітов Нұрлан Асқарұлы" in html and "admin@korkyt.kz" in html and "+7 777 123 45 67" in html
    bad = client.post("/profile", data={"action": "info", "full_name": "1"}).get_data(as_text=True)
    assert "alert-error" in bad
    assert "Сейітов Нұрлан Асқарұлы" in client.get("/profile").get_data(as_text=True)
    client.post("/logout")
    login(client, "030512501238", "Student2026")
    html = client.get("/profile").get_data(as_text=True)
    assert 'name="full_name"' in html and 'name="group_name"' in html
    client.post("/profile", data={"action": "info", "full_name": "Жаңа Есім Студент", "group_name": "сиб-24-1",
                                  "phone": "", "gender": "", "email": ""})
    html = client.get("/profile").get_data(as_text=True)
    assert "Жаңа Есім Студент" in html and "СИБ-24-1" in html
    client.post("/logout")
    login(client, "dekanat1", "Dekanat2026")          # декан аты-жөнін профильде өзгертпейді
    assert 'name="full_name"' not in client.get("/profile").get_data(as_text=True)


def test_avatar_upload_and_access(client, app):
    login(client, "030512501238", "Student2026")
    r = client.post("/profile/avatar", data={"avatar": (io.BytesIO(PNG), "me.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Профиль суреті жаңартылды" in r.get_data(as_text=True)
    row = app.extensions["db"].execute(
        "SELECT id, avatar FROM users WHERE username='030512501238'").fetchone()
    assert row["avatar"].endswith(".png")
    assert client.get(f"/avatar/{row['id']}").data == PNG
    # бөтен адам суретті көре алмайды, деканат қызметкері көреді
    other = app.test_client()
    assert other.get(f"/avatar/{row['id']}").status_code == 404
    login(other, "dekanat1", "Dekanat2026")
    assert other.get(f"/avatar/{row['id']}").status_code == 200
    # сурет емес файл және тым үлкен файл қабылданбайды
    r = client.post("/profile/avatar", data={"avatar": (io.BytesIO(b"<svg></svg>"), "x.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Тек JPG, PNG немесе WEBP" in r.get_data(as_text=True)
    big = io.BytesIO(PNG + b"\x00" * (2 * 1024 * 1024))
    r = client.post("/profile/avatar", data={"avatar": (big, "big.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "2 МБ-тан аспауы керек" in r.get_data(as_text=True)
    client.post("/profile/avatar", data={"action": "delete"})
    assert client.get(f"/avatar/{row['id']}").status_code == 404


def test_cli_set_password(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["set-password", "admin"], input="Dean#2026x\nDean#2026x\n")
    assert result.exit_code == 0 and "OK: admin" in result.output
    assert login(app.test_client(), "admin", "Dean#2026x").headers["Location"].endswith("/admin")


def test_cli_set_password_rejects_weak(app):
    result = app.test_cli_runner().invoke(args=["set-password", "admin"], input="weakpass1\nweakpass1\n")
    assert result.exit_code != 0


def test_default_hours_are_enforced(tmp_path, monkeypatch):
    monkeypatch.delenv("QUEUE_DEMO", raising=False)
    application = create_app({"DATABASE": str(tmp_path / "d.db"), "SECRET_KEY": "x"})
    assert application.config["CHECK_HOURS"] is True
    application.extensions["db"].close()
