"""
Қорқыт Ата атындағы Қызылорда университеті туралы анықтамалық деректер (басты бет үшін).

Дереккөздер (2026 жылғы қараша айында тексерілді):
  * korkyt.edu.kz/article/379        — «Университетке 85 жыл» (тарих, сандар, рейтингтер)
  * korkyt.edu.kz/ru/matbase/2       — «9 оқу корпусы» (мекенжайлар, 5-корпус)
  * korkyt.edu.kz/partners           — серіктес ЖОО тізімі
  * korkyt.edu.kz/en/article/2080    — академиялық ұтқырлық, 2025–2026 оқу жылы
  * ru.wikipedia.org — «Кызылординский университет имени Коркыт ата»
  * korkyt.edu.kz/article/2053       — 2025–2026 оқу жылына қабылданған студенттер (4 252)
  * kyzylorda-news.kz, 23.10.2025     — 2024–2025 оқу жылындағы білім алушылар саны (11,7 мың)

Деректер өзгеруі мүмкін, сондықтан ресми сайтқа сілтеме де беріледі.
Мәтіндер бір жерде сақталады: оларды жаңарту үшін шаблонды өзгерту қажет емес.
"""

OFFICIAL_SITE = "https://korkyt.edu.kz"

CONTACTS = {
    "phone": "8 777 777 77 77",
    "admission_phone": "8 777 777 77 77",
    "email": "ksu@korkyt.kz",
    "main_building": {"kk": "Қызылорда қ., Әйтеке би к-сі, 29А (бас корпус, ректорат)",
                      "ru": "г. Кызылорда, ул. Айтеке би, 29А (главный корпус, ректорат)"},
}

# Негізгі сандар
FACTS = [
    {"value": "1937", "kk": "құрылған жылы", "ru": "год основания"},
    {"value": "9", "kk": "оқу корпусы", "ru": "учебных корпусов"},
    {"value": "11 700+", "kk": "білім алушы (2024–2025 оқу жылының қорытындысы)",
     "ru": "обучающихся (итоги 2024–2025 учебного года)"},
    {"value": "4 252", "kk": "студент 2025–2026 оқу жылында қабылданды",
     "ru": "студента принято в 2025–2026 учебном году"},
    {"value": "115", "kk": "білім беру бағдарламасы", "ru": "образовательных программ"},
    {"value": "5", "kk": "институт", "ru": "институтов"},
]

ABOUT = {
    "kk": ("Қорқыт Ата атындағы Қызылорда университеті — Сыр өңіріндегі ең ірі көпсалалы "
           "жоғары оқу орны, білім мен ғылымның ғана емес, рухани-мәдени өмірдің де орталығы. "
           "Университет Ұлы дала ойшылы Қорқыт Атаның есімімен аталады. Мұнда бакалавриат, "
           "магистратура және докторантура бағдарламалары бойынша мамандар даярланады. "
           "Өңір экономикасындағы мамандардың шамамен 80 пайызы — осы университеттің түлектері. "
           "2020 жылдан бастап университет коммерциялық емес акционерлік қоғам болып жұмыс істейді."),
    "ru": ("Кызылординский университет имени Коркыт Ата — крупнейший многопрофильный вуз "
           "Приаралья, центр не только образования и науки, но и духовно-культурной жизни региона. "
           "Университет носит имя великого мыслителя степи Коркыт Ата. Здесь готовят специалистов "
           "по программам бакалавриата, магистратуры и докторантуры. Около 80% специалистов в "
           "экономике области — выпускники университета. С 2020 года вуз работает как "
           "некоммерческое акционерное общество."),
}

INSTITUTES = {
    "kk": ["Гуманитарлық-педагогикалық институт", "Педагогика және дәстүрлі өнер институты",
           "Жаратылыстану институты", "Инженерлік-технологиялық институт",
           "Экономика және құқық институты"],
    "ru": ["Гуманитарно-педагогический институт", "Институт педагогики и традиционного искусства",
           "Институт естествознания", "Инженерно-технологический институт",
           "Институт экономики и права"],
}

# Тарихи кезеңдер
HISTORY = [
    {"year": "1937",
     "kk": "Қиыр Шығыстан көшірілген Корей педагогикалық институты негізінде Қызылорда педагогикалық институты ашылды: 4 факультет, 372 студент, 27 оқытушы.",
     "ru": "На базе переведённого с Дальнего Востока Корейского педагогического института открыт Кызылординский пединститут: 4 факультета, 372 студента, 27 преподавателей."},
    {"year": "1941–1945",
     "kk": "Соғыс жылдары институт базасында эвакуацияланған Киев және Харьков университеттері жұмыс істеді.",
     "ru": "В годы войны на базе института работали эвакуированные Киевский и Харьковский университеты."},
    {"year": "1952",
     "kk": "Педагогикалық институтқа Н. В. Гоголь есімі берілді.",
     "ru": "Пединституту присвоено имя Н. В. Гоголя."},
    {"year": "1976",
     "kk": "Жамбыл гидромелиоративтік-құрылыс институтының Қызылорда филиалы ашылды (кейін — Ы. Жақаев атындағы политехникалық институт).",
     "ru": "Открыт Кызылординский филиал Джамбулского гидромелиоративно-строительного института (позже — политехнический институт им. И. Жахаева)."},
    {"year": "1992",
     "kk": "Педагогикалық институтқа Қорқыт Ата есімі берілді.",
     "ru": "Пединституту присвоено имя Коркыт Ата."},
    {"year": "1996",
     "kk": "Қорқыт Ата атындағы Қызылорда гуманитарлық университеті болып қайта құрылды.",
     "ru": "Реорганизован в Кызылординский гуманитарный университет им. Коркыт Ата."},
    {"year": "1998",
     "kk": "Гуманитарлық университет пен Ы. Жақаев атындағы политехникалық институт біріктіріліп, Қорқыт Ата атындағы Қызылорда мемлекеттік университеті құрылды.",
     "ru": "Гуманитарный университет и политехнический институт им. И. Жахаева объединены в Кызылординский государственный университет им. Коркыт Ата."},
    {"year": "2020",
     "kk": "«Қорқыт Ата атындағы Қызылорда университеті» коммерциялық емес акционерлік қоғамы болып қайта құрылды.",
     "ru": "Реорганизован в НАО «Кызылординский университет имени Коркыт Ата»."},
]


# ---------------------------------------------------------------------------
# 5-оқу корпусы
# ---------------------------------------------------------------------------
BUILDING_5 = {
    "address": {"kk": "Қызылорда қ., Абай даңғылы, 66А (қазіргі Н. Назарбаев даңғылы, 15)",
                "ru": "г. Кызылорда, пр. Абая, 66А (ныне пр. Н. Назарбаева, 15)"},
    "intro": {
        "kk": "5-оқу корпусы — университеттің IT және цифрлық технологиялар бағытындағы негізгі ғимараттарының бірі. 2023 жылдан бастап мұнда студенттер мен қызметкерлерге заманауи әрі жайлы орта жасау үшін ауқымды қайта жаңарту және абаттандыру жұмыстары жүргізілуде.",
        "ru": "Учебный корпус №5 — одно из главных зданий университета по направлению IT и цифровых технологий. С 2023 года здесь ведутся масштабные работы по реконструкции и благоустройству, чтобы создать современную и комфортную среду для студентов и сотрудников.",
    },
    "features": [
        {"kk": "10 компьютерлік сынып (Intel Core i5, 8–16 ГБ жедел жады)",
         "ru": "10 компьютерных классов (Intel Core i5, 8–16 ГБ ОЗУ)"},
        {"kk": "№321 «3D printing» зертханасы: 3D-принтерлер мен 3D-сканер («3D-технологиялар негіздері» пәні)",
         "ru": "Лаборатория №321 «3D printing»: 3D-принтеры и 3D-сканер (дисциплина «Основы 3D-технологий»)"},
        {"kk": "№316 робототехника зертханасы: Turtlebot3, LEGO Mindstorms EV3, Ultimate Robot Kit, квадрокоптерлер",
         "ru": "Лаборатория робототехники №316: Turtlebot3, LEGO Mindstorms EV3, Ultimate Robot Kit, квадрокоптеры"},
        {"kk": "Дрондарды еркін ұшыруға арналған қорғаныс торы бар зертхана: магистрлік және дипломдық зерттеулерге",
         "ru": "Лаборатория со страховочной сеткой для свободного полёта дронов: для магистерских и дипломных исследований"},
        {"kk": "2023 жылдан бері жүріп жатқан қайта жаңарту және абаттандыру жұмыстары",
         "ru": "Реконструкция и благоустройство, начатые в 2023 году"},
    ],
    "map_url": "https://yandex.ru/maps/org/163479318914/",
}

# Барлық оқу корпустары (ресми «9 оқу корпусы» бетінен)
BUILDINGS = [
    {"no": {"kk": "Бас корпус", "ru": "Главный"}, "kk": "Әйтеке би к-сі, 29А", "ru": "ул. Айтеке би, 29А",
     "note": {"kk": "ректорат", "ru": "ректорат"}},
    {"no": "1", "kk": "Әбілқайыр хан к-сі, 50А", "ru": "ул. Абулхаир хана, 50А", "note": None},
    {"no": "2", "kk": "Қорқыт Ата к-сі, 36А", "ru": "ул. Коркыт Ата, 36А", "note": None},
    {"no": "3", "kk": "Ыбырай Жақаев к-сі, 55", "ru": "ул. Ыбрая Жакаева, 55",
     "note": {"kk": "әскери кафедра", "ru": "военная кафедра"}},
    {"no": "4", "kk": "Ыбырай Жақаев к-сі, 57", "ru": "ул. Ыбрая Жакаева, 57",
     "note": {"kk": "физика зертханалары", "ru": "физические лаборатории"}},
    {"no": "5", "kk": "Абай даңғылы, 66А", "ru": "пр. Абая, 66А",
     "note": {"kk": "IT, 3D, робототехника", "ru": "IT, 3D, робототехника"}},
    {"no": "6", "kk": "Жақаев к-сі, 11", "ru": "ул. Жакаева, 11", "note": None},
    {"no": "7", "kk": "Төле би к-сі, 36", "ru": "ул. Толе би, 36", "note": None},
    {"no": "8", "kk": "Төле би к-сі, 36 к1", "ru": "ул. Толе би, 36 к1", "note": None},
    {"no": "9", "kk": "Амангелді Иманов к-сі, 60", "ru": "ул. Амангельды Иманова, 60",
     "note": {"kk": "биология, спорт кешені, зоология мұражайы", "ru": "биология, спорткомплекс, зоологический музей"}},
]

# ---------------------------------------------------------------------------
# Серіктестер
# ---------------------------------------------------------------------------
# Ресми тізімдегі жазбалар саны, ел бойынша (korkyt.edu.kz/partners).
# Бетте тек жалпы сан көрсетіледі (елдер мен ұйымдар саны).
PARTNER_COUNTRIES = [
    {"kk": "Ресей", "ru": "Россия", "n": 44},
    {"kk": "Әзірбайжан", "ru": "Азербайджан", "n": 12},
    {"kk": "Түркия", "ru": "Турция", "n": 12},
    {"kk": "Өзбекстан", "ru": "Узбекистан", "n": 12},
    {"kk": "Қырғызстан", "ru": "Кыргызстан", "n": 9},
    {"kk": "Оңтүстік Корея", "ru": "Южная Корея", "n": 9},
    {"kk": "Болгария", "ru": "Болгария", "n": 7},
    {"kk": "Беларусь", "ru": "Беларусь", "n": 5},
    {"kk": "Қытай", "ru": "Китай", "n": 3},
    {"kk": "Польша", "ru": "Польша", "n": 3},
    {"kk": "Германия", "ru": "Германия", "n": 2},
    {"kk": "Литва", "ru": "Литва", "n": 2},
    {"kk": "Португалия", "ru": "Португалия", "n": 2},
    {"kk": "Ұлыбритания", "ru": "Великобритания", "n": 2},
    {"kk": "Аргентина", "ru": "Аргентина", "n": 1},
    {"kk": "Бельгия", "ru": "Бельгия", "n": 1},
    {"kk": "Венгрия", "ru": "Венгрия", "n": 1},
    {"kk": "Индонезия", "ru": "Индонезия", "n": 1},
    {"kk": "Испания", "ru": "Испания", "n": 1},
    {"kk": "Италия", "ru": "Италия", "n": 1},
    {"kk": "Латвия", "ru": "Латвия", "n": 1},
    {"kk": "Ливан", "ru": "Ливан", "n": 1},
    {"kk": "Молдова", "ru": "Молдова", "n": 1},
    {"kk": "Сауд Арабиясы", "ru": "Саудовская Аравия", "n": 1},
    {"kk": "Үндістан", "ru": "Индия", "n": 1},
    {"kk": "Франция", "ru": "Франция", "n": 1},
]

# Таңдаулы серіктестер (атаулары халықаралық түрде)
FEATURED_PARTNERS = [
    {"name": "Seoul National University of Science and Technology", "country": {"kk": "Оңтүстік Корея", "ru": "Южная Корея"},
     "kk": "2025–2026 оқу жылында 6 студент оқуда; IT саласында жоғары мектеп ашу жобасы",
     "ru": "6 студентов в 2025–2026 уч. году; проект высшей школы в сфере IT"},
    {"name": "University of Łódź", "country": {"kk": "Польша", "ru": "Польша"},
     "kk": "Келісім бойынша жыл сайын 25 студентке дейін оқиды",
     "ru": "По соглашению — до 25 студентов ежегодно"},
    {"name": "HOWEST University of Applied Sciences", "country": {"kk": "Бельгия", "ru": "Бельгия"},
     "kk": "Академиялық ұтқырлық бағдарламасы", "ru": "Программа академической мобильности"},
    {"name": "Kangnam University", "country": {"kk": "Оңтүстік Корея", "ru": "Южная Корея"},
     "kk": "Академиялық ұтқырлық", "ru": "Академическая мобильность"},
    {"name": "Ankara University", "country": {"kk": "Түркия", "ru": "Турция"},
     "kk": "Түркиядағы серіктес ЖОО-лардың бірі", "ru": "Один из партнёров в Турции"},
    {"name": "Osmaniye Korkut Ata University", "country": {"kk": "Түркия", "ru": "Турция"},
     "kk": "Қорқыт Ата есімін алған бауырлас университет", "ru": "Побратим, также носящий имя Коркыт Ата"},
    {"name": "Kazan Federal University", "country": {"kk": "Ресей", "ru": "Россия"},
     "kk": "Ресейдегі жетекші серіктестердің бірі", "ru": "Один из ведущих партнёров в России"},
    {"name": "HSE University", "country": {"kk": "Ресей", "ru": "Россия"},
     "kk": "«Экономика жоғары мектебі» ұлттық зерттеу университеті", "ru": "НИУ «Высшая школа экономики»"},
    {"name": "Vytautas Magnus University", "country": {"kk": "Литва", "ru": "Литва"},
     "kk": "Еуропалық серіктес", "ru": "Европейский партнёр"},
    {"name": "University of Florence", "country": {"kk": "Италия", "ru": "Италия"},
     "kk": "Еуропалық серіктес", "ru": "Европейский партнёр"},
    {"name": "University of Reading", "country": {"kk": "Ұлыбритания", "ru": "Великобритания"},
     "kk": "Британиялық серіктес", "ru": "Британский партнёр"},
    {"name": "CNRS", "country": {"kk": "Франция", "ru": "Франция"},
     "kk": "Франция Ұлттық ғылыми зерттеулер орталығы", "ru": "Национальный центр научных исследований Франции"},
    {"name": "Kyrgyz-Turkish Manas University", "country": {"kk": "Қырғызстан", "ru": "Кыргызстан"},
     "kk": "Орталық Азиядағы серіктес", "ru": "Партнёр в Центральной Азии"},
    {"name": "National University of Uzbekistan", "country": {"kk": "Өзбекстан", "ru": "Узбекистан"},
     "kk": "Мирзо Ұлықбек атындағы ұлттық университет", "ru": "Национальный университет им. Мирзо Улугбека"},
    {"name": "Baku State University", "country": {"kk": "Әзірбайжан", "ru": "Азербайджан"},
     "kk": "Әзірбайжандағы серіктес", "ru": "Партнёр в Азербайджане"},
    {"name": "Universitas Gadjah Mada", "country": {"kk": "Индонезия", "ru": "Индонезия"},
     "kk": "Азиядағы серіктес", "ru": "Партнёр в Азии"},
]

MOBILITY_NOTE = {
    "kk": "2025–2026 оқу жылының күзгі семестрінде студенттер Оңтүстік Корея, Бельгия, Польша, Түркия, Өзбекстан, Әзірбайжан және Қырғызстан университеттерінде оқуын жалғастыруда.",
    "ru": "В осеннем семестре 2025–2026 учебного года студенты продолжают обучение в вузах Южной Кореи, Бельгии, Польши, Турции, Узбекистана, Азербайджана и Кыргызстана.",
}


def partner_totals() -> tuple[int, int]:
    """(елдер саны, ресми тізімдегі жазбалар саны)."""
    return len(PARTNER_COUNTRIES), sum(c["n"] for c in PARTNER_COUNTRIES)


# Ағылшынша нұсқа: әр тізім жоғарыдағы деректермен бірдей ретте
EN = {
    "main_building": "Kyzylorda, 29A Aiteke Bi St. (main building, rectorate)",
    "facts": ["year founded", "academic buildings", "students (2024–2025 academic year)",
              "students admitted in 2025–2026", "educational programmes", "institutes"],
    "about": ("Korkyt Ata Kyzylorda University is the largest multidisciplinary university of the Aral Sea region, "
              "a centre not only of education and science but also of the region's spiritual and cultural life. "
              "The university is named after Korkyt Ata, the great thinker of the steppe. It trains specialists in "
              "bachelor's, master's and doctoral programmes. About 80% of specialists in the regional economy are its "
              "graduates. Since 2020 the university has operated as a non-profit joint-stock company."),
    "institutes": ["Humanitarian and Pedagogical Institute", "Institute of Pedagogy and Traditional Art",
                   "Institute of Natural Sciences", "Institute of Engineering and Technology",
                   "Institute of Economics and Law"],
    "history": [
        "Kyzylorda Pedagogical Institute opened on the basis of the Korean Pedagogical Institute moved from the Far East: 4 faculties, 372 students, 27 teachers.",
        "During the war, the evacuated Kyiv and Kharkiv universities worked on the institute's premises.",
        "The pedagogical institute was named after N. V. Gogol.",
        "The Kyzylorda branch of the Dzhambul Hydro-Reclamation and Construction Institute opened (later the I. Zhakhaev Polytechnic Institute).",
        "The pedagogical institute was named after Korkyt Ata.",
        "Reorganised into Korkyt Ata Kyzylorda Humanitarian University.",
        "The humanitarian university and the I. Zhakhaev Polytechnic Institute merged into Korkyt Ata Kyzylorda State University.",
        "Reorganised into the non-profit JSC “Korkyt Ata Kyzylorda University”.",
    ],
    "b5_address": "Kyzylorda, 66A Abai Ave. (now 15 N. Nazarbayev Ave.)",
    "b5_intro": ("Academic building No. 5 is one of the university's main buildings for IT and digital technologies. "
                 "Since 2023 large-scale reconstruction and improvement work has been under way here to create a modern, "
                 "comfortable environment for students and staff."),
    "b5_features": ["10 computer classrooms (Intel Core i5, 8–16 GB RAM)",
                    "Lab No. 321 “3D printing”: 3D printers and a 3D scanner (course “Fundamentals of 3D Technologies”)",
                    "Robotics lab No. 316: Turtlebot3, LEGO Mindstorms EV3, Ultimate Robot Kit, quadcopters",
                    "Lab with a safety net for free drone flights: for master's and diploma research",
                    "Reconstruction and improvement started in 2023"],
    "mobility": ("In the autumn semester of the 2025–2026 academic year, students continue their studies at universities "
                 "in South Korea, Belgium, Poland, Turkey, Uzbekistan, Azerbaijan and Kyrgyzstan."),
}
EN_COUNTRY = {"Оңтүстік Корея": "South Korea", "Польша": "Poland", "Бельгия": "Belgium", "Түркия": "Turkey",
              "Ресей": "Russia", "Литва": "Lithuania", "Италия": "Italy", "Ұлыбритания": "United Kingdom",
              "Франция": "France", "Қырғызстан": "Kyrgyzstan", "Өзбекстан": "Uzbekistan", "Әзірбайжан": "Azerbaijan",
              "Индонезия": "Indonesia"}


def _localized_en() -> dict:
    """Ағылшынша деректер: мәтіндер EN-нен, қалғаны (сандар, атаулар) ортақ."""
    data = localized("ru")
    data["about"] = EN["about"]
    data["facts"] = [{"value": f["value"], "label": label} for f, label in zip(FACTS, EN["facts"])]
    data["institutes"] = EN["institutes"]
    data["history"] = [{"year": h["year"], "text": text} for h, text in zip(HISTORY, EN["history"])]
    data["contacts"] = {**CONTACTS, "main_building": EN["main_building"]}
    data["building5"] = {**data["building5"], "address": EN["b5_address"], "intro": EN["b5_intro"],
                         "features": [{"text": f} for f in EN["b5_features"]]}
    data["featured_partners"] = [{"name": p["name"], "country": EN_COUNTRY.get(p["country"]["kk"], p["country"]["ru"]),
                                  "text": ""} for p in FEATURED_PARTNERS]
    data["mobility"] = EN["mobility"]
    return data


def localized(lang: str) -> dict:
    """Шаблонға беруге дайын, бір тілге аударылған деректер."""
    if lang == "en":
        return _localized_en()
    lang = lang if lang in ("kk", "ru") else "kk"

    def pick(value):
        return value[lang] if isinstance(value, dict) else value

    countries, entries = partner_totals()
    return {
        "site": OFFICIAL_SITE,
        "about": ABOUT[lang],
        "facts": [{"value": f["value"], "label": f[lang]} for f in FACTS],
        "institutes": INSTITUTES[lang],
        "history": [{"year": h["year"], "text": h[lang]} for h in HISTORY],
        "contacts": {**CONTACTS, "main_building": CONTACTS["main_building"][lang]},
        "building5": {
            "address": BUILDING_5["address"][lang],
            "intro": BUILDING_5["intro"][lang],
            "features": [{"text": f[lang]} for f in BUILDING_5["features"]],
            "map_url": BUILDING_5["map_url"],
        },
        "buildings": [{"no": pick(b["no"]), "address": b[lang],
                       "note": pick(b["note"]) if b["note"] else ""} for b in BUILDINGS],
        "partners_total": {"countries": countries, "entries": entries},
        "featured_partners": [{"name": p["name"], "country": p["country"][lang], "text": p[lang]}
                              for p in FEATURED_PARTNERS],
        "mobility": MOBILITY_NOTE[lang],
    }
