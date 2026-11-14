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
    assert "Абай даңғылы, 66А" in chatbot.answer("деканат қайда", "kk", CTX)["reply"]
    assert "ksu@korkyt.kz" in chatbot.answer("контакты, телефон", "ru", CTX)["reply"]


def test_unknown_language_falls_back_to_kk():
    assert chatbot.answer("сәлем", "en", CTX)["suggestions"] == chatbot.SUGGESTIONS["kk"]


def test_long_message_is_truncated():
    assert len(chatbot.normalize("а" * 5000)) <= chatbot.MAX_MESSAGE_LEN


def test_html_is_not_echoed():
    r = chatbot.answer("<script>alert(1)</script> талон", "kk", CTX)
    assert "<script>" not in r["reply"]
