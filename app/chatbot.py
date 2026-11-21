"""
Көмекші-чат: сұрақты кілт сөздер бойынша танып, дайын жауап береді.

Сыртқы AI-сервис қолданылмайды — интернетсіз жұмыс істейді, жауаптар болжамды
және тесттермен тексеріледі. Жұмыс уақыты, кезек, студенттің өз талоны, бүгінгі/ертеңгі
күн және хабарландырулар туралы жауаптар нақты деректерден құрылады (web.py ctx береді).

Мүмкіндіктері:
- сұрақ тілін өзі анықтайды (қазақ әріптері → kk, орысша сөздер → ru);
- қате терілген сөздерді де таниды (difflib, ұқсастық ≥ 0.8);
- әр жауаптан кейін тақырыпқа сай келесі сұрақтарды ұсынады.
"""
from __future__ import annotations

import difflib
import re

MAX_MESSAGE_LEN = 300
FUZZY_CUTOFF = 0.8      # қате терілген сөзді тану шегі
FUZZY_MIN_LEN = 6       # қысқа сөздер (қайда, табло, талон) тек дәл сәйкестікпен ізделеді
FUZZY_WEIGHT = 0.6      # қате терілген сөз дәл сәйкестіктен әлсіз саналады

# Ниет (intent) -> кілт сөздердің түбірлері. Тізім реті — тең ұпайдағы басымдық.
INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("whoami", ("who am i", "my account", "мен кіммін", "мен кім", "кім екенім", "кто я", "кем я", "мой аккаунт", "менің аккаунт")),
    ("about", ("what is this site", "about the site", "about the system", "electronic queue", "бұл не сайт", "бұл сайт", "сайт туралы", "кезек туралы", "электронды кезек", "электрондық кезек",
               "жүйе туралы", "что это за сайт", "что за сайт", "о сайте", "о системе", "электронная очередь",
               "что это", "бұл не")),
    ("my_ticket", ("my turn", "my ticket", "when will i", "my number", "менің кезег", "менің талон", "кезегім", "талоным", "мой талон", "моя очеред",
                   "моей очеред", "когда меня", "когда вызов", "қашан шақыр", "мені қашан",
                   "қанша қалды", "сколько осталось", "мой номер")),
    ("help", ("көмек", "помощ", "what can you", "не істей аласың", "не істей аласыз", "что умеешь", "мүмкіндік", "help")),
    ("deputy", ("орынбасар", "замдекан", "зам декан", "заместител")),
    ("password", ("password", "forgot", "құпиясөз", "құпия сөз", "пароль", "ұмыт", "забыл")),
    ("staff", ("қызметкер", "әдіскер", "сотрудник", "оператор", "растау", "подтвержд")),
    ("cancel", ("cancel", "бас тарт", "отмен", "өшір", "удали")),
    ("services", ("services", "what can i do", "қызметтер", "қызмет түр", "қандай қызмет", "услуг", "что можно сделать", "виды")),
    ("notify", ("notification", "sound", "vibrat", "хабарлама", "уведомл", "дыбыс", "звук", "вибра", "ескерт")),
    ("announce", ("announcement", "news", "хабарланд", "объявлен", "жаңалық", "новост")),
    ("day", ("open today", "open tomorrow", "work today", "work tomorrow", "holiday", "бүгін жұмыс", "ертең жұмыс", "бүгін деканат", "ертең деканат", "деканат бүгін",
             "деканат ертең", "бүгін аш", "ертең аш", "сегодня работ", "завтра работ", "деканат сегодня",
             "деканат завтра", "мереке", "праздн", "жұмыс істей ме", "работает ли")),
    ("queue", ("how many people", "how long", "queue now", "қанша адам", "кезек ұзын", "неше адам", "күту", "сколько", "ожида", "долго",
               "кезек қазір", "очередь сейчас")),
    ("hours", ("working hours", "opening hours", "lunch", "break time", "schedule", "жұмыс уақыт", "сағат", "қашан аш", "қашан жаб", "түскі", "түстенү", "обед",
               "үзіліс", "перерыв", "время работ", "график", "открыт", "закрыт", "демалыс күн",
               "выходн")),
    ("board", ("board", "табло",)),
    ("profile", ("profile", "avatar", "photo", "профиль", "аватар", "сурет", "фото", "фио", "аты-жөнім", "тобымды", "группу")),
    ("register", ("register", "sign up", "create an account", "тіркел", "регистр", "аккаунт", "кабинет аш")),
    ("ticket", ("ticket", "get in line", "join the queue", "талон", "кезекке тұр", "кезек ал", "очеред", "встать", "записат")),
    ("documents", ("document", "certificate", "transcript", "құжат", "анықтама", "справк", "документ", "транскрипт", "академ", "retake",
                   "қайта тапсыр", "пересдач", "өтініш", "заявлен")),
    ("address", ("where", "address", "located", "room", "мекенжай", "қайда", "корпус", "адрес", "где", "находит", "қалай бар", "добрат",
                 "аудитория", "кабинет")),
    ("contacts", ("phone", "contact", "e-mail", "email", "телефон", "байланыс", "контакт", "email", "почта", "хабарлас", "позвон")),
    ("thanks", ("thanks", "thank you", "рахмет", "рақмет", "спасибо", "благодар")),
    ("greet", ("hello", "good morning", "good afternoon", "сәлем", "салем", "қайырлы", "привет", "здравств", "добрый")),
]

KAZAKH_LETTERS = set("әғқңөұүһі")
RU_WORDS = {"как", "где", "что", "когда", "сколько", "мой", "моя", "мне", "можно", "есть", "нужно",
            "какие", "какой", "почему", "очередь", "время", "услуги", "завтра", "сегодня", "работает"}
EN_WORDS = {"how", "what", "where", "when", "is", "are", "my", "the", "can", "i", "do", "hello", "hi",
            "thanks", "thank", "ticket", "queue", "help", "who", "open", "tomorrow", "today"}
RU_PREFIXES = ("работ", "очеред", "услуг", "здравств", "спасиб", "привет", "получ", "находит")

# Әр ниеттен кейін ұсынылатын келесі сұрақтар (SUGGEST кілттері)
FOLLOW_UP = {
    "ticket": ("my_ticket", "queue", "services"),
    "my_ticket": ("queue", "cancel", "address"),
    "queue": ("my_ticket", "hours", "ticket"),
    "hours": ("day", "queue", "address"),
    "day": ("hours", "announce", "ticket"),
    "register": ("ticket", "profile", "password"),
    "services": ("ticket", "documents", "queue"),
    "address": ("hours", "contacts", "ticket"),
    "about": ("ticket", "services", "hours"),
    "whoami": ("my_ticket", "profile", "ticket"),
}
DEFAULT_SUGGEST = ("ticket", "my_ticket", "hours", "address")

SUGGEST = {
    "kk": {"ticket": "Талонды қалай алуға болады?", "my_ticket": "Менің кезегім қашан?",
           "queue": "Кезекте қанша адам бар?", "hours": "Жұмыс уақыты қандай?",
           "day": "Ертең деканат жұмыс істей ме?", "address": "Деканат қайда орналасқан?",
           "services": "Қандай қызметтер бар?", "cancel": "Талоннан қалай бас тартамын?",
           "announce": "Хабарландырулар бар ма?", "contacts": "Деканат телефоны қандай?",
           "profile": "Профильді қалай толтырамын?", "password": "Құпиясөзді ұмыттым",
           "documents": "Қандай құжат керек?"},
    "ru": {"ticket": "Как получить талон?", "my_ticket": "Когда моя очередь?",
           "queue": "Сколько человек в очереди?", "hours": "Какое время работы?",
           "day": "Работает ли деканат завтра?", "address": "Где находится деканат?",
           "services": "Какие есть услуги?", "cancel": "Как отменить талон?",
           "announce": "Есть ли объявления?", "contacts": "Какой телефон деканата?",
           "profile": "Как заполнить профиль?", "password": "Я забыл пароль",
           "documents": "Какие документы нужны?"},
    "en": {"ticket": "How do I get a ticket?", "my_ticket": "When is my turn?",
           "queue": "How many people are in the queue?", "hours": "What are the working hours?",
           "day": "Is the dean's office open tomorrow?", "address": "Where is the dean's office?",
           "services": "What services are there?", "cancel": "How do I cancel a ticket?",
           "announce": "Are there any announcements?", "contacts": "What is the dean's office phone?",
           "profile": "How do I fill in my profile?", "password": "I forgot my password",
           "documents": "What documents do I need?"},
}

TEXTS = {
    "kk": {
        "greet": "Сәлеметсіз бе! Мен деканат кезегінің көмекшісімін. Талон, кезек, жұмыс уақыты, қызметтер немесе деканаттың орны туралы сұраңыз. Не істей алатынымды білу үшін «көмек» деп жазыңыз.",
        "about": "Бұл — Қорқыт Ата атындағы Қызылорда университеті деканатының электрондық кезегі. Студент талонды телефоннан алады, кезегін онлайн көреді, кезегі жақындағанда және шақырылғанда хабар алады. Декан мен орынбасар кезекті бір панельден басқарады, ал табло кімнің қай аудиторияға шақырылғанын көрсетеді.",
        "whoami_guest": "Сіз әлі жүйеге кірген жоқсыз. «Кіру» батырмасы арқылы логин мен құпиясөзді жазыңыз.",
        "whoami": "Сіз — {name}, рөліңіз: {role}, логиніңіз: {login}.",
        "help": "Мен мыналарға көмектесемін: талонды қалай алу; менің кезегім қашан (кірген болсаңыз); кезекте қанша адам бар; жұмыс уақыты және бүгін не ертең деканат жұмыс істей ме; қызметтер тізімі; деканат қайда; байланыс; хабарландырулар; профиль мен құпиясөз.",
        "thanks": "Оқасы жоқ! Тағы сұрағыңыз болса, жаза беріңіз.",
        "ticket": "Талон алу үшін: 1) «Тіркелу» бетінде аты-жөніңізді, логин мен құпиясөзді жазып тіркеліңіз; 2) «Кіру» арқылы кабинетке кіріңіз; 3) қызметті таңдап, «Талон алу» батырмасын басыңыз. Кезегіңіз жақындағанда және шақырылғанда телефоныңыз дыбыс береді.",
        "register": "Студент «Тіркелу» бетінде аты-жөнін, логин мен құпиясөзді енгізеді — аккаунт бірден ашылады. Тобын, телефонын, e-mail мен суретін кейін «Профиль» бетінде толтырады. Декан мен орынбасардың аккаунтын администратор ашады.",
        "cancel": "Талоннан бас тарту үшін кабинеттегі «Белсенді талондарым» бөлімінде ✕ батырмасын немесе талон бетінде «Талоннан бас тарту» батырмасын басыңыз.",
        "documents": "Деканатқа келгенде жеке куәлігіңізді және студенттік билетіңізді ала келуді ұсынамыз. Өтініш, академиялық демалыс немесе Retake сияқты қызметтерге қажетті құжаттардың нақты тізімін деканаттан нақтылаңыз.",
        "password": "Құпиясөзді ұмытсаңыз, «Кіру» бетіндегі «Құпиясөзді ұмыттыңыз ба?» сілтемесін басыңыз: логиніңізді, тіркелгенде берілген қалпына келтіру кодын және жаңа құпиясөзді жазасыз. Кодыңыз жоқ болса, деканатқа не администраторға хабарласыңыз — олар уақытша құпиясөз береді, кірген кезде оны өзіңіздікіне ауыстырасыз.",
        "staff": "Декан мен декан орынбасарының аккаунтын администратор «Басқару → Пайдаланушылар → Жаңа аккаунт жасау» арқылы ашады. Олар өз аудиториясын «Профиль» бетінде жазады. Панельде «Келесіні шақыру», «Аяқталды», «Келмеді» және «Үзіліс» батырмалары бар.",
        "deputy": "Декан орынбасары студенттерді қабылдайды және студенттер мен орынбасарлар аккаунттарын басқарады. Декан мен администратордың аккаунттарын өзгерте алмайды.",
        "address": "Деканат №5 оқу корпусында орналасқан: 2-қабат, оң жақ блоктың ең шеткі кабинеті. Корпустың мекенжайы: {b5}.",
        "contacts": "Телефон: {phone}. Қабылдау комиссиясы: {admission}. E-mail: {email}.",
        "hours": "Деканат жұмыс уақыты: {days}, {hours}. {lunch}{breaks}Қазір: {status}.",
        "lunch": "Түскі үзіліс: {lunch}. ",
        "breaks": "Қысқа үзілістер: {breaks}. ",
        "queue_head": "Қазір кезекте барлығы {total} адам.",
        "queue_line": "{name}: {waiting} адам, шамамен {estimate} мин",
        "queue_empty": "Қазір кезек бос — талон алсаңыз, бірден шақырыласыз.",
        "services_head": "Деканат қызметтері (жақшада — бір студентті қабылдау уақыты): ",
        "services_line": "{name} (~{minutes} мин)",
        "my_login": "Талоныңызды көру үшін жүйеге кіріңіз — сонда нөміріңізді, алдыңызда қанша адам барын және шамамен күту уақытын айтамын.",
        "my_none": "Бүгін белсенді талоныңыз жоқ. Кабинетте қызметті таңдап, «Талон алу» батырмасын басыңыз.",
        "my_waiting": "{number} ({service}): алдыңызда {ahead} адам, шамамен {estimate} мин.",
        "my_called": "{number}: сізді шақырды! {window} аудиторияға өтіңіз.",
        "when_today": "Бүгін", "when_tomorrow": "Ертең",
        "day_work": "{when} деканат жұмыс істейді: {hours}.",
        "day_short": "{when} қысқартылған жұмыс күні: {hours}. {note}",
        "day_weekend": "{when} демалыс күні — деканат жұмыс істемейді.",
        "day_holiday": "{when} мереке — деканат жұмыс істемейді. {note}",
        "announce_head": "Деканаттың хабарландырулары: ",
        "announce_none": "Қазір хабарландыру жоқ.",
        "board": "Электрондық табло «Табло» бетінде: онда шақырылған талондар аудиториясымен және бүкіл кезек көрсетіледі. Деканат алдындағы экранда да осы бет ашық тұрады.",
        "profile": "«Профиль» бетінде аты-жөніңізді, тобыңызды, телефон, e-mail, жынысты және суретті өзгерте аласыз, құпиясөзді де сонда ауыстырасыз.",
        "notify": "Алдыңызда 2 адам қалғанда талон бетінде ескерту шығып, телефон дыбыс береді; шақырылғанда тағы дыбыс пен діріл болады. Ол үшін талон бетін ашық ұстаңыз.",
        "fallback": "Мен тек электрондық кезек пен талон туралы сұрақтарға жауап беремін. Басқа сұрақтарыңыз болса, деканатқа барғанда маманнан сұрап біле аласыз. Деканат телефоны: {phone}.",
        "status_open": "деканат ашық",
        "status_closed": "деканат жабық",
        "status_lunch": "түскі үзіліс",
        "status_break": "қысқа үзіліс",
    },
    "ru": {
        "greet": "Здравствуйте! Я помощник электронной очереди деканата. Спросите о талоне, очереди, времени работы, услугах или о том, где находится деканат. Чтобы узнать, что я умею, напишите «помощь».",
        "about": "Это электронная очередь деканата Кызылординского университета имени Коркыт Ата. Студент берёт талон с телефона, видит свою очередь онлайн и получает сигнал, когда очередь подходит и когда его вызывают. Декан и заместитель управляют очередью из одной панели, а табло показывает, кого и в какую аудиторию вызвали.",
        "whoami_guest": "Вы ещё не вошли в систему. Нажмите «Войти» и введите логин и пароль.",
        "whoami": "Вы — {name}, роль: {role}, логин: {login}.",
        "help": "Я помогу: как получить талон; когда моя очередь (если вы вошли); сколько человек в очереди; время работы и работает ли деканат сегодня или завтра; список услуг; где деканат; контакты; объявления; профиль и пароль.",
        "thanks": "Пожалуйста! Если будут ещё вопросы — пишите.",
        "ticket": "Чтобы получить талон: 1) зарегистрируйтесь на странице «Регистрация» — ФИО, логин и пароль; 2) войдите через «Войти»; 3) выберите услугу и нажмите «Получить талон». Когда очередь подойдёт и когда вас вызовут, телефон подаст сигнал.",
        "register": "Студент вводит на странице «Регистрация» ФИО, логин и пароль — аккаунт открывается сразу. Группу, телефон, e-mail и фото он заполняет позже в «Профиле». Аккаунты декана и заместителя создаёт администратор.",
        "cancel": "Чтобы отменить талон, нажмите ✕ в разделе «Мои активные талоны» в кабинете или «Отменить талон» на странице талона.",
        "documents": "Рекомендуем взять с собой удостоверение личности и студенческий билет. Точный список документов для заявления, академического отпуска или Retake уточните в деканате.",
        "password": "Если забыли пароль, на странице «Войти» нажмите «Забыли пароль?»: введите логин, код восстановления, выданный при регистрации, и новый пароль. Если кода нет, обратитесь в деканат или к администратору — вам выдадут временный пароль, при входе вы смените его на свой.",
        "staff": "Аккаунты декана и заместителя декана создаёт администратор: «Управление → Пользователи → Создать аккаунт». Свою аудиторию они указывают в «Профиле». В панели есть кнопки «Вызвать следующего», «Завершить», «Не явился» и «Перерыв».",
        "deputy": "Заместитель декана принимает студентов и ведёт аккаунты студентов и заместителей. Аккаунты декана и администратора изменять не может.",
        "address": "Деканат находится в учебном корпусе №5: 2-й этаж, крайний кабинет правого блока. Адрес корпуса: {b5}.",
        "contacts": "Телефон: {phone}. Приёмная комиссия: {admission}. E-mail: {email}.",
        "hours": "Время работы деканата: {days}, {hours}. {lunch}{breaks}Сейчас: {status}.",
        "lunch": "Обед: {lunch}. ",
        "breaks": "Короткие перерывы: {breaks}. ",
        "queue_head": "Сейчас в очереди всего {total} чел.",
        "queue_line": "{name}: {waiting} чел., примерно {estimate} мин",
        "queue_empty": "Сейчас очередь пуста — если возьмёте талон, вас вызовут сразу.",
        "services_head": "Услуги деканата (в скобках — время приёма одного студента): ",
        "services_line": "{name} (~{minutes} мин)",
        "my_login": "Чтобы я подсказал по вашему талону, войдите в систему — тогда назову номер, сколько человек перед вами и примерное время ожидания.",
        "my_none": "Сегодня у вас нет активного талона. Выберите услугу в кабинете и нажмите «Получить талон».",
        "my_waiting": "{number} ({service}): перед вами {ahead} чел., примерно {estimate} мин.",
        "my_called": "{number}: вас вызвали! Пройдите в аудиторию {window}.",
        "when_today": "Сегодня", "when_tomorrow": "Завтра",
        "day_work": "{when} деканат работает: {hours}.",
        "day_short": "{when} сокращённый рабочий день: {hours}. {note}",
        "day_weekend": "{when} выходной — деканат не работает.",
        "day_holiday": "{when} праздник — деканат не работает. {note}",
        "announce_head": "Объявления деканата: ",
        "announce_none": "Сейчас объявлений нет.",
        "board": "Электронное табло — на странице «Табло»: там видны вызванные талоны с аудиторией и вся очередь. Эта же страница открыта на экране у деканата.",
        "profile": "В «Профиле» можно изменить ФИО, группу, телефон, e-mail, пол и фото, а также сменить пароль.",
        "notify": "Когда перед вами останется 2 человека, на странице талона появится предупреждение и телефон подаст сигнал; при вызове — снова сигнал и вибрация. Для этого держите страницу талона открытой.",
        "fallback": "Я отвечаю только на вопросы об электронной очереди и талонах. Если у вас другой вопрос, задайте его специалисту, когда придёте в деканат. Телефон деканата: {phone}.",
        "status_open": "деканат открыт",
        "status_closed": "деканат закрыт",
        "status_lunch": "обеденный перерыв",
        "status_break": "короткий перерыв",
    },
    "en": {
        "greet": "Hello! I am the dean's office queue assistant. Ask about tickets, the queue, working hours, services or where the dean's office is. Type “help” to see what I can do.",
        "about": "This is the electronic queue of the dean's office of Korkyt Ata Kyzylorda University. Students take a ticket from their phone, see their place in the queue online and get a signal when their turn is near and when they are called. The dean and deputy manage the queue from one panel, and the board shows who is called to which room.",
        "whoami_guest": "You are not logged in yet. Press “Log in” and enter your login and password.",
        "whoami": "You are {name}, role: {role}, login: {login}.",
        "help": "I can help with: how to get a ticket; when my turn is (if you are logged in); how many people are in the queue; working hours and whether the dean's office is open today or tomorrow; the list of services; where the dean's office is; contacts; announcements; profile and password.",
        "thanks": "You're welcome! Write if you have more questions.",
        "ticket": "To get a ticket: 1) register on the “Register” page with your full name, login and password; 2) log in; 3) choose a service and press “Get a ticket”. Your phone will beep when your turn is near and when you are called.",
        "register": "A student enters a full name, login and password on the “Register” page — the account opens immediately. Group, phone, e-mail and photo are filled in later in “Profile”. Dean and deputy accounts are created by the administrator.",
        "cancel": "To cancel a ticket, press ✕ in “My active tickets” in your account or “Cancel ticket” on the ticket page.",
        "documents": "We recommend bringing your ID card and student card. Please check the exact list of documents for applications, academic leave or Retake at the dean's office.",
        "password": "If you forgot your password, press “Forgot your password?” on the login page: enter your login, the recovery code given at registration and a new password. If you have no code, contact the dean's office or the administrator — they will give you a temporary password, which you will change when you log in.",
        "staff": "Dean and deputy dean accounts are created by the administrator: “Management → Users → Create account”. They enter their room in “Profile”. The panel has “Call next”, “Finish”, “No-show” and “Break” buttons.",
        "deputy": "The deputy dean receives students and manages student and deputy accounts. They cannot change the dean's or administrator's accounts.",
        "address": "The dean's office is in academic building No. 5: 2nd floor, the last room of the right wing. Building address: {b5}.",
        "contacts": "Phone: {phone}. Admissions office: {admission}. E-mail: {email}.",
        "hours": "Dean's office hours: {days}, {hours}. {lunch}{breaks}Now: {status}.",
        "lunch": "Lunch: {lunch}. ",
        "breaks": "Short breaks: {breaks}. ",
        "queue_head": "There are {total} people in the queue now.",
        "queue_line": "{name}: {waiting} people, about {estimate} min",
        "queue_empty": "The queue is empty now — if you take a ticket, you will be called right away.",
        "services_head": "Dean's office services (time to serve one student in brackets): ",
        "services_line": "{name} (~{minutes} min)",
        "my_login": "Log in so I can tell you about your ticket — the number, how many people are ahead of you and the estimated wait.",
        "my_none": "You have no active ticket today. Choose a service in your account and press “Get a ticket”.",
        "my_waiting": "{number} ({service}): {ahead} people ahead of you, about {estimate} min.",
        "my_called": "{number}: you have been called! Please go to room {window}.",
        "when_today": "Today", "when_tomorrow": "Tomorrow",
        "day_work": "{when} the dean's office is open: {hours}.",
        "day_short": "{when} is a shortened working day: {hours}. {note}",
        "day_weekend": "{when} is a day off — the dean's office is closed.",
        "day_holiday": "{when} is a holiday — the dean's office is closed. {note}",
        "announce_head": "Dean's office announcements: ",
        "announce_none": "There are no announcements now.",
        "board": "The electronic board is on the “Board” page: it shows called tickets with their room and the whole queue. The same page is on the screen near the dean's office.",
        "profile": "In “Profile” you can change your full name, group, phone, e-mail, gender and photo, and also change your password.",
        "notify": "When 2 people are left ahead of you, a warning appears on the ticket page and your phone beeps; when you are called, it beeps and vibrates again. Keep the ticket page open for this.",
        "fallback": "I answer only questions about the electronic queue and tickets. For other questions, please ask a specialist at the dean's office. Dean's office phone: {phone}.",
        "status_open": "the dean's office is open",
        "status_closed": "the dean's office is closed",
        "status_lunch": "lunch break",
        "status_break": "short break",
    },
}

SUGGESTIONS = {lang: [SUGGEST[lang][k] for k in DEFAULT_SUGGEST] for lang in SUGGEST}


class _Blank(dict):
    """format_map үшін: жоқ мән бос жол болып шығады (KeyError болмайды)."""

    def __missing__(self, key):
        return ""


def normalize(text: str) -> str:
    """Кіші әріп, артық бос орындар мен тыныс белгілерін алып тастау."""
    text = (text or "")[:MAX_MESSAGE_LEN].lower().replace("ё", "е")
    text = re.sub(r"[^\w\s\-]", " ", text)
    return " ".join(text.split())


def detect_lang(text: str, default: str) -> str:
    """Сұрақтың тілі: қазақ әріптері болса — kk, орысша сөздер болса — ru, әйтпесе бет тілі."""
    norm = normalize(text)
    if KAZAKH_LETTERS & set(norm):
        return "kk"
    words = norm.split()
    if any(w in RU_WORDS or w.startswith(RU_PREFIXES) for w in words):
        return "ru"
    if words and re.fullmatch(r"[a-z0-9\s\-]+", norm) and any(w in EN_WORDS for w in words):
        return "en"
    return default


def _hit(key: str, norm: str, words: list[str]) -> float:
    """Кілт сөздің салмағы: дәл бар — 1, қате терілгені — FUZZY_WEIGHT, жоқ — 0."""
    if key in norm:
        return 1.0
    if " " in key or len(key) < FUZZY_MIN_LEN:
        return 0.0
    prefixes = [w[:len(key)] for w in words if len(w) >= len(key) - 1]
    close = difflib.get_close_matches(key, prefixes, n=1, cutoff=FUZZY_CUTOFF)
    return FUZZY_WEIGHT if close else 0.0


def detect_intent(text: str) -> str | None:
    """Ең көп кілт сөз сәйкес келген ниетті қайтарады; тізім реті — басымдық."""
    norm = normalize(text)
    if not norm:
        return None
    words = norm.split()
    best, best_score = None, 0
    for name, keys in INTENTS:
        score = sum(_hit(k, norm, words) for k in keys)
        if score > best_score:
            best, best_score = name, score
    return best


def answer(text: str, lang: str, ctx: dict) -> dict:
    """Сұраққа жауап: {'intent', 'reply', 'suggestions', 'lang'}."""
    lang = detect_lang(text, lang if lang in TEXTS else "kk")
    tr = TEXTS[lang]
    intent = detect_intent(text)
    builder = BUILDERS.get(intent)
    if builder:
        reply = builder(tr, ctx, lang, text)
    elif intent in ("address", "contacts"):
        contacts = ctx.get("contacts_" + lang) or ctx.get("contacts", {})  # мекенжай сұрақ тілінде
        reply = tr[intent].format_map(_Blank(contacts))
    elif intent:
        reply = tr[intent]
    else:
        reply = tr["fallback"].format(phone=ctx.get("contacts", {}).get("phone", ""))
    keys = FOLLOW_UP.get(intent, DEFAULT_SUGGEST)
    return {"intent": intent, "reply": reply, "lang": lang,
            "suggestions": [SUGGEST[lang][k] for k in keys]}


def _hours_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    s = ctx.get("schedule", {})
    lunch = tr["lunch"].format(lunch=s["lunch"]) if s.get("lunch") else ""
    breaks = tr["breaks"].format(breaks=", ".join(s["breaks"])) if s.get("breaks") else ""
    status = tr["status_" + s.get("status", "closed")]
    return tr["hours"].format(days=s.get("days", ""), hours=s.get("hours", ""),
                              lunch=lunch, breaks=breaks, status=status)


def _queue_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    services = ctx.get("services", [])
    total = sum(s["waiting"] for s in services)
    if total == 0:
        return tr["queue_empty"]
    lines = [tr["queue_line"].format(name=s["name_" + lang], waiting=s["waiting"],
                                     estimate=s["estimate"]) for s in services if s["waiting"]]
    return tr["queue_head"].format(total=total) + " " + "; ".join(lines) + "."


def _services_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    lines = [tr["services_line"].format(name=s["name_" + lang], minutes=s.get("minutes", ""))
             for s in ctx.get("services", [])]
    return tr["services_head"] + "; ".join(lines) + "."


def _my_ticket_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    """Кірген студенттің бүгінгі белсенді талондары: нөмір, алдындағылар, болжам."""
    tickets = ctx.get("my_tickets")
    if tickets is None:
        return tr["my_login"]
    if not tickets:
        return tr["my_none"]
    parts = []
    for tk in tickets:
        key = "my_called" if tk["status"] == "called" else "my_waiting"
        parts.append(tr[key].format(number=tk["number"], service=tk["service_" + lang],
                                    ahead=tk["ahead"], estimate=tk["estimate"], window=tk["window"] or "—"))
    return " ".join(parts)


def _day_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    """Бүгін не ертең деканат жұмыс істей ме (мереке, демалыс, қысқартылған күн)."""
    tomorrow = any(w in normalize(text) for w in ("ертең", "завтра", "tomorrow"))
    plan = ctx.get("tomorrow" if tomorrow else "today") or {}
    when = tr["when_tomorrow" if tomorrow else "when_today"]
    kind = plan.get("kind", "work")
    return tr["day_" + kind].format(when=when, hours=plan.get("hours", ""), note=plan.get("note", "")).strip()


def _announce_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    items = ctx.get("announcements") or []
    return tr["announce_head"] + " ".join(items) if items else tr["announce_none"]


def _whoami_reply(tr: dict, ctx: dict, lang: str, text: str) -> str:
    me = ctx.get("me")
    if not me:
        return tr["whoami_guest"]
    return tr["whoami"].format(name=me["name"], role=me["role_" + lang], login=me["login"])


BUILDERS = {"whoami": _whoami_reply, "hours": _hours_reply, "queue": _queue_reply, "services": _services_reply,
            "my_ticket": _my_ticket_reply, "day": _day_reply, "announce": _announce_reply}
