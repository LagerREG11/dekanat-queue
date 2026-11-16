"""Көмекші-чат модулінің тесттері (chatbot.py)."""
import pytest

from app import chatbot

CTX = {
    "schedule": {"days": "Дс–Жм", "hours": "09:00–18:00", "lunch": "13:00–14:00",
                 "breaks": ["11:00–11:15"], "status": "open"},
    "services": [{"code": "A", "name_kk": "Анықтама алу", "name_ru": "Справка", "waiting": 2, "estimate": 8},
                 {"code": "B", "name_kk": "Өтініш", "name_ru": "Заявление", "waiting": 0, "estimate": 0}],
    "contacts": {"main": "Әйтеке би, 29А", "b5": "Абай даңғылы, 66А", "phone": "+7 7242 26-27-14",
                 "admission": "+7 7242 71-07-45", "email": "ksu@korkyt.kz"},
}


@pytest.mark.parametrize("text,intent", [
    ("Сәлем!", "greet"),
    ("Талонды қалай алуға болады?", "ticket"),
    ("Как получить талон?", "ticket"),
    ("Жұмыс уақыты қандай?", "hours"),
    ("Когда обед?", "hours"),
    ("Кезекте қанша адам бар?", "queue"),
    ("Сколько ждать?", "queue"),
    ("Деканат қайда орналасқан?", "address"),
    ("Телефон нөмірі", "contacts"),
    ("Құпиясөзді ұмыттым", "password"),
    ("Талоннан қалай бас тартамын?", "cancel"),
    ("Анықтамаға қандай құжат керек?", "documents"),
    ("Как зарегистрироваться?", "register"),
    ("Декан орынбасары не істей алады?", "deputy"),
    ("Рахмет", "thanks"),
])
def test_detect_intent(text, intent):
    assert chatbot.detect_intent(text) == intent


@pytest.mark.parametrize("text", ["", "   ", "???", "asdfgh qwerty"])
def test_unknown_goes_to_fallback(text):
    r = chatbot.answer(text, "kk", CTX)
    assert r["intent"] is None and "+7 7242 26-27-14" in r["reply"]


def test_hours_reply_uses_schedule():
    r = chatbot.answer("жұмыс уақыты", "kk", CTX)
    assert "09:00–18:00" in r["reply"] and "13:00–14:00" in r["reply"] and "11:00–11:15" in r["reply"]
    assert "деканат ашық" in r["reply"]


def test_hours_reply_without_lunch_during_lunch():
    ctx = dict(CTX, schedule={"days": "Пн–Пт", "hours": "09:00–18:00", "lunch": "", "breaks": [], "status": "lunch"})
    r = chatbot.answer("время работы", "ru", ctx)
    assert "Обед:" not in r["reply"] and "обеденный перерыв" in r["reply"]


def test_queue_reply_lists_only_nonempty():
    r = chatbot.answer("кезекте қанша адам", "kk", CTX)
    assert "2 адам" in r["reply"] and "Анықтама алу" in r["reply"] and "Өтініш" not in r["reply"]


def test_queue_reply_empty():
    ctx = dict(CTX, services=[])
    assert "бос" in chatbot.answer("кезекте қанша адам", "kk", ctx)["reply"]


def test_address_and_contacts_use_ctx():
    r = chatbot.answer("деканат қайда", "kk", CTX)["reply"]
    assert "2-қабат" in r and "оң жақ блоктың" in r and "Абай даңғылы, 66А" in r
    assert "ksu@korkyt.kz" in chatbot.answer("контакты, телефон", "ru", CTX)["reply"]


def test_unknown_language_falls_back_to_kk():
    assert chatbot.answer("сәлем", "en", CTX)["suggestions"] == chatbot.SUGGESTIONS["kk"]


def test_long_message_is_truncated():
    assert len(chatbot.normalize("а" * 5000)) <= chatbot.MAX_MESSAGE_LEN


def test_html_is_not_echoed():
    r = chatbot.answer("<script>alert(1)</script> талон", "kk", CTX)
    assert "<script>" not in r["reply"]


# ---------------- Жақсартылған чат-бот ----------------
def test_language_detected_from_question():
    assert chatbot.answer("Где находится деканат?", "kk", CTX)["lang"] == "ru"
    assert "учебном корпусе" in chatbot.answer("Где находится деканат?", "kk", CTX)["reply"]
    assert chatbot.answer("Деканат қайда?", "ru", CTX)["lang"] == "kk"
    assert chatbot.answer("талон", "ru", CTX)["lang"] == "ru"          # анық белгі жоқ — бет тілі


def test_typos_are_understood():
    assert chatbot.detect_intent("рахмат") == "thanks"
    assert chatbot.detect_intent("рассписание графк работы") == "hours"
    assert chatbot.detect_intent("рагистрация") == "register"


def test_my_ticket_reply_states():
    assert "кіріңіз" in chatbot.answer("менің кезегім қашан", "kk", CTX)["reply"]
    ctx = dict(CTX, my_tickets=[])
    assert "белсенді талоныңыз жоқ" in chatbot.answer("менің талоным", "kk", ctx)["reply"]
    ctx = dict(CTX, my_tickets=[{"number": "A-004", "status": "waiting", "ahead": 2, "estimate": 8,
                                 "window": None, "service_kk": "Анықтама", "service_ru": "Справка"}])
    assert "A-004 (Анықтама): алдыңызда 2 адам, шамамен 8 мин" in chatbot.answer("менің кезегім", "kk", ctx)["reply"]
    ctx["my_tickets"][0].update(status="called", window="214А")
    assert "Пройдите в аудиторию 214А" in chatbot.answer("когда моя очередь", "ru", ctx)["reply"]


def test_today_tomorrow_services_announcements_help():
    ctx = dict(CTX, today={"kind": "work", "hours": "09:00–18:00", "note": ""},
               tomorrow={"kind": "holiday", "hours": "", "note": "Тәуелсіздік күні"},
               announcements=["13:00-ден кейін декан жиналыста."])
    assert "Бүгін деканат жұмыс істейді: 09:00–18:00" in chatbot.answer("бүгін жұмыс істей ме", "kk", ctx)["reply"]
    assert "мереке" in chatbot.answer("ертең жұмыс істей ме", "kk", ctx)["reply"]
    assert "Завтра праздник" in chatbot.answer("работает ли деканат завтра", "ru", ctx)["reply"]
    assert "Анықтама алу" in chatbot.answer("қандай қызметтер бар", "kk", ctx)["reply"]
    assert "декан жиналыста" in chatbot.answer("хабарландыру бар ма", "kk", ctx)["reply"]
    assert "хабарландыру жоқ" in chatbot.answer("хабарландыру", "kk", CTX)["reply"]
    assert "талонды қалай алу" in chatbot.answer("көмек", "kk", CTX)["reply"]


def test_follow_up_suggestions_depend_on_topic():
    r = chatbot.answer("талон алу", "kk", CTX)
    assert r["suggestions"][0] == "Менің кезегім қашан?"


def test_about_and_whoami():
    for q in ("электронды кезек туралы айтшы", "бұл не сайт?", "что это за сайт"):
        assert chatbot.detect_intent(q) == "about", q
    assert "электрондық кезегі" in chatbot.answer("бұл не сайт?", "kk", CTX)["reply"]
    assert "кірген жоқсыз" in chatbot.answer("мен кіммін", "kk", CTX)["reply"]
    ctx = dict(CTX, me={"name": "Темірлан Бегайдаров", "login": "begaydarovv", "role_kk": "Студент", "role_ru": "Студент"})
    assert "Темірлан Бегайдаров" in chatbot.answer("мен кіммін", "kk", ctx)["reply"]
    assert "логин: begaydarovv" in chatbot.answer("кто я", "ru", ctx)["reply"]
