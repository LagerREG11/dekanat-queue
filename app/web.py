"""
Қорқыт Ата атындағы Қызылорда университеті — деканаттың электрондық кезегі.
Веб-интерфейс (Flask). Іске қосу: flask --app app.web run  немесе  python run.py

Үш рөл:
  student  — тіркеледі, кабинетте талон алады, өз талондарын көреді
  dekanat  — декан: студенттерді шақырады, аккаунттарды басқарады (администратордан басқа)
  admin    — әкімші: аккаунттар, қызметтер, талондардағы қателерді түзету, журнал
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from . import chatbot, university_info
from . import db as repo
from . import service as ql
from .i18n import DEFAULT_LANG, LANGUAGES, translate

BASE_DIR = Path(__file__).resolve().parent.parent  # жобаның түбірі
ROLE_HOME = {ql.STUDENT: "student_cabinet", ql.DEKANAT: "dekanat_panel",
             ql.DEPUTY: "admin_panel", ql.ADMIN: "admin_panel"}
CHAT_LIMIT = 30  # бір IP-ден минутына неше чат хабарламасы
AVATAR_MAX_BYTES = 2 * 1024 * 1024  # профиль суреті 2 МБ-тан аспайды


# ---------------------------------------------------------------------------
# Қолданба фабрикасы (тесттерде басқа баптаулармен жасауға болады)
# ---------------------------------------------------------------------------
def _default_config() -> dict:
    """Қолданбаның әдепкі баптаулары (орта айнымалылары арқылы өзгертіледі)."""
    return {
        "DATABASE": str(BASE_DIR / "instance" / "dekanat.db"),
        "SECRET_KEY": os.environ.get("SECRET_KEY") or _load_or_create_secret(),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.environ.get("COOKIE_SECURE") == "1",
        "CHECK_HOURS": os.environ.get("QUEUE_DEMO", "0") != "1",  # QUEUE_DEMO=1 — уақыт тексерілмейді
        "RATE_LIMIT": 5,            # бір IP-ден минутына неше талон / тіркелу
        "LOGIN_LIMIT": 10,          # бір IP-ден минутына неше кіру әрекеті
        "NOW": _local_clock(os.environ.get("APP_TIMEZONE", DEFAULT_TIMEZONE)),  # тесттерде ауыстырылады
        "PUBLIC_URL": os.environ.get("PUBLIC_URL", ""),  # QR-кодтағы мекенжай (телефондар үшін)
        "SHOW_DEMO_ACCOUNTS": os.environ.get("SHOW_DEMO_ACCOUNTS", "1") != "0",  # хостингте 0
        "MAX_CONTENT_LENGTH": 3 * 1024 * 1024,  # сұрау көлемі (сурет жүктеу үшін) 3 МБ-тан аспайды
        "TESTING": False,
    }


def _open_startup_db(app: Flask) -> None:
    """Дерекқорды жасап, кестелер мен бастапқы деректерді дайындайды."""
    if app.config["DATABASE"] != ":memory:":
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    if app.config["DATABASE"] == ":memory:":
        raise ValueError("Веб-қолданбаға файлдағы дерекқор керек (DATABASE=':memory:' болмайды)")
    conn = repo.connect(app.config["DATABASE"])
    repo.init_db(conn)
    repo.seed(conn, app.config["NOW"]())
    # Бұл қосылым тек іске қосу мен тесттерге арналған. Беттер әр сұрауда өз қосылымын
    # ашады (db() функциясын қараңыз): бір қосылымды бірнеше ағын бірге қолданса,
    # сұраулар бір-біріне кедергі жасап, қате шығады.
    app.extensions["db"] = conn
    app.extensions["rate"] = defaultdict(deque)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(_default_config())
    if config:
        app.config.update(config)
    _open_startup_db(app)

    for register in ROUTE_GROUPS:
        register(app)
    return app


DEFAULT_TIMEZONE = "Asia/Qyzylorda"  # Қызылорда, UTC+5


def _local_clock(tz_name: str):
    """Деканаттың жергілікті уақытын қайтаратын функция.

    Хостинг серверлері UTC уақытымен жұмыс істейді, сондықтан уақыт белдеуін
    сервер баптауына емес, zoneinfo арқылы тікелей қолданамыз. Уақыт белдеуі
    табылмаса (мысалы, tzdata орнатылмаған Windows) — компьютердің уақыты алынады.
    """
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now
    return lambda: datetime.now(zone).replace(tzinfo=None)


def _load_or_create_secret() -> str:
    path = BASE_DIR / "instance" / "secret_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    return key


# ---------------------------------------------------------------------------
# Көмекші функциялар
# ---------------------------------------------------------------------------
def db():
    """Ағымдағы сұрауға арналған жеке SQLite қосылымы (сұрау соңында жабылады)."""
    if "db_conn" not in g:
        g.db_conn = repo.connect(current_app.config["DATABASE"])
    return g.db_conn


def now() -> datetime:
    return current_app.config["NOW"]()


def lang() -> str:
    code = session.get("lang", DEFAULT_LANG)
    return code if code in LANGUAGES else DEFAULT_LANG


def t(key: str) -> str:
    return translate(key, lang())


def public_url() -> str:
    """Телефоннан ашуға болатын сайт мекенжайы (QR-код үшін).

    Сервер Wi-Fi желісіне ашылған болса (--lan), іске қосу кезінде анықталған мекенжай
    қолданылады; әйтпесе браузер ашқан мекенжай алынады.
    """
    return current_app.config.get("PUBLIC_URL") or request.host_url


def local_ips() -> list[str]:
    """Компьютердің жергілікті желідегі IPv4 мекенжайлары (127.* және 169.254.* қоспағанда)."""
    ips: list[str] = []
    try:
        # UDP «қосылуы» ешқандай пакет жібермейді, тек шығыс интерфейсті анықтайды
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith(("127.", "169.254.", "0."))]


def qr_svg(data: str, scale: int = 5) -> str:
    """Мәтінді QR-код SVG суретіне айналдырады (segno кітапханасы)."""
    import io

    import segno
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=scale, border=2,
                                     dark="#122c63", light="#ffffff", xmldecl=False)
    return buf.getvalue().decode("utf-8")


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def current_user():
    """Сессиядағы пайдаланушы (бұғатталған болса — шығарып тастаймыз)."""
    if "user" not in g:
        uid = session.get("user_id")
        user = repo.get_user(db(), uid) if uid else None
        if user is not None and not user["is_active"]:
            session.pop("user_id", None)
            user = None
        g.user = user
    return g.user


def role_required(*roles):
    """Бетке тек көрсетілген рөлдер кіре алады."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("login", role=roles[0], next=request.path))
            if user["role"] not in roles:
                flash("err_forbidden", "error")
                return redirect(url_for(ROLE_HOME[user["role"]]))
            return view(*args, **kwargs)
        return wrapper
    return decorator


def safe_next(value: str | None, default: str = "/") -> str:
    """Ашық редиректтен қорғау: тек сайт ішіндегі жолдар."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    return value


def rate_limited(bucket: str, limit: int) -> bool:
    ip = request.remote_addr or "?"
    q = current_app.extensions["rate"][f"{bucket}:{ip}"]
    current = time.monotonic()
    while q and current - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(current)
    return False


def flash_error(e: ql.QueueError) -> None:
    flash(e.code, "error")


def schedule() -> ql.Schedule:
    """Ағымдағы жұмыс кестесі (әкімші/декан орынбасары өзгерте алады)."""
    if "schedule" not in g:
        g.schedule = repo.get_schedule(db())
    return g.schedule


def overrides() -> dict:
    """Декан белгілеген ерекше күндер (қысқартылған күн, қосымша демалыс)."""
    if "overrides" not in g:
        g.overrides = repo.get_overrides(db())
    return g.overrides


def open_now() -> bool:
    """Талон беруге бола ма? (08:45–18:00, үзілістерден тыс). Демо-режимде уақыт тексерілмейді."""
    return ql.can_take_ticket(now(), schedule(), overrides()) or not current_app.config["CHECK_HOURS"]


def booking_text() -> str:
    """Талон қашан беріле бастайтынын адамға түсінікті мәтінмен береді (қазір берілсе — бос)."""
    n = now()
    start = ql.next_booking_time(n, schedule(), overrides())
    if start is None or start == n:
        return ""
    hhmm = start.strftime("%H:%M")
    if start.date() == n.date():
        return t("booking_today").format(time=hhmm)
    if start.date() == n.date() + timedelta(days=1):
        return t("booking_tomorrow").format(time=hhmm)
    days = t("days_short").split(",")
    return t("booking_on").format(date=start.strftime("%d.%m"), day=days[start.weekday()], time=hhmm)


def schedule_info() -> dict:
    """Кестені беттерде және чатта көрсетуге ыңғайлы түрге келтіреді."""
    s = schedule()
    hhmm = lambda x: x.strftime("%H:%M")
    days = t("days_short").split(",")
    workdays = list(s.workdays)
    if workdays == list(range(workdays[0], workdays[-1] + 1)) and len(workdays) > 2:
        days_text = f"{days[workdays[0]]}–{days[workdays[-1]]}"
    else:
        days_text = ", ".join(days[d] for d in workdays)
    n = now()
    plan = ql.day_plan(n.date(), s, overrides())
    today = plan.schedule
    if today is None:
        status = "closed"
    else:
        pause = ql.current_pause(n, today)
        in_hours = today.open_at <= n.time() < today.close_at
        status = pause if pause and in_hours else ("open" if ql.is_open(n, today) else "closed")
    return {"days": days_text, "hours": f"{hhmm(s.open_at)}–{hhmm(s.close_at)}",
            "lunch": f"{hhmm(s.lunch_from)}–{hhmm(s.lunch_to)}" if s.lunch_from else "",
            "breaks": [f"{hhmm(a)}–{hhmm(b)}" for a, b in s.breaks], "status": status,
            "today_kind": plan.kind, "today_note": plan.note,
            "today_hours": f"{hhmm(today.open_at)}–{hhmm(today.close_at)}" if today else "",
            "booking_from": (datetime.combine(n.date(), s.open_at)
                             - timedelta(minutes=ql.BOOKING_LEAD_MINUTES)).strftime("%H:%M"),
            "booking": booking_text()}


def notices() -> list[dict]:
    """Барлық беттің жоғарғы жағындағы хабарландырулар: деканның хабарламалары және
    бүгін қысқартылған күн / қосымша демалыс болса — сол туралы ескерту."""
    items = []
    info = schedule_info()
    if info["today_kind"] == ql.SHORT:
        text = t("notice_short_day").format(hours=info["today_hours"])
        items.append({"kind": "urgent", "text": f"{text} {info['today_note']}".strip()})
    elif info["today_kind"] == ql.HOLIDAY and info["today_note"]:
        items.append({"kind": "urgent", "text": info["today_note"]})
    for a in repo.active_announcements(db(), now()):
        items.append({"kind": "info", "text": a["text"]})
    return items


def calendar_view() -> dict:
    """Ағымдағы айдың күнтізбесі (басты бет үшін)."""
    n = now()
    weeks = ql.month_calendar(n.year, n.month, n.date(), schedule(), overrides())
    idx = 0 if lang() == "kk" else 1
    for week in weeks:
        for cell in week:
            if cell is None:
                continue
            plan = cell["plan"]
            cell["kind"] = plan.kind
            cell["hours"] = (f"{plan.schedule.open_at.strftime('%H:%M')}–"
                             f"{plan.schedule.close_at.strftime('%H:%M')}") if plan.schedule else ""
            cell["label"] = (plan.holiday[idx] if plan.holiday else "") or plan.note
    return {"weeks": weeks, "month": t("months").split(",")[n.month - 1], "year": n.year,
            "days": t("days_short").split(",")}


def _register_helpers(app: Flask) -> None:
    @app.context_processor
    def inject():
        user = current_user()
        return {"t": t, "lang": lang(), "languages": LANGUAGES, "csrf_token": csrf_token,
                "public_url": public_url,
                "demo": not app.config["CHECK_HOURS"], "user": user,
                "show_demo_accounts": app.config["SHOW_DEMO_ACCOUNTS"],
                "role_home": ROLE_HOME, "roles": ql.ROLES, "sched": schedule_info,
                "notices": notices,
                "manager_roles": ql.MANAGER_ROLES, "staff_roles": ql.STAFF_ROLES}

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("WTF_CSRF_DISABLED"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                if request.is_json:
                    return jsonify(error=t("err_csrf")), 400
                flash("err_csrf", "error")
                return redirect(request.path)



def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        return resp



def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", message=t("err_404")), 404

    @app.errorhandler(413)
    def too_large(_e):
        flash("err_avatar_size", "error")
        return redirect(url_for("profile"))


def _ticket_view(ticket) -> dict:
    """Талон туралы JSON/шаблон үшін деректер (жеке деректерсіз)."""
    conn = db()
    ahead = repo.people_ahead(conn, ticket)
    service = repo.get_service(conn, ticket["service_id"])
    est = repo.estimate_for_service(conn, service, ahead) if ticket["status"] == ql.WAITING else 0
    return {
        "number": ticket["number"],
        "status": ticket["status"],
        "status_text": t("st_" + ticket["status"]),
        "ahead": ahead,
        "estimate": est,
        "service_minutes": ql_minutes(service["avg_minutes"]),
        "window": ticket["window_no"],
        "recall": ticket["recall_count"],
        "late": (ticket["status"] == ql.WAITING and current_app.config["CHECK_HOURS"]
                 and not ql.can_be_served_today(now(), est, schedule())),
    }


# ---------------------------------------------------------------------------
# Барлығына ашық беттер
# ---------------------------------------------------------------------------
def _register_public_routes(app: Flask) -> None:

    @app.get("/lang/<code>")
    def set_lang(code):
        if code in LANGUAGES:
            session["lang"] = code
        return redirect(safe_next(request.args.get("next")))

    @app.get("/")
    def index():
        services = repo.services_overview(db(), now())
        return render_template(
            "index.html", services=services, uni=university_info.localized(lang()),
            total_waiting=sum(s["waiting"] for s in services),
            open_windows=max((s["windows"] for s in services), default=0),
            is_open=open_now(), cal=calendar_view())



def _register_ticket_routes(app: Flask) -> None:
    @app.get("/ticket/<token>")
    def ticket_page(token):
        ticket = repo.get_ticket_by_token(db(), token)
        if ticket is None:
            abort(404)
        user = current_user()
        return render_template("ticket.html", ticket=ticket, view=_ticket_view(ticket),
                               service_name=ticket["name_" + lang()],
                               is_owner=user is not None and user["id"] == ticket["user_id"])

    @app.get("/api/ticket/<token>")
    def api_ticket(token):
        ticket = repo.get_ticket_by_token(db(), token)
        if ticket is None:
            return jsonify(error=t("err_not_found")), 404
        return jsonify(_ticket_view(ticket))

    @app.get("/qr.svg")
    def qr_code():
        """Сайттың өз мекенжайының QR-коды (сырттан мәтін қабылдамайды)."""
        resp = current_app.response_class(qr_svg(public_url()), mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "no-store"
        return resp



def _register_chat_routes(app: Flask) -> None:
    @app.post("/api/chat")
    def api_chat():
        """Көмекші-чат: {"message": "..."} -> {"reply": "...", "suggestions": [...]}."""
        if rate_limited("chat", CHAT_LIMIT):
            return jsonify(error=t("err_rate")), 429
        data = request.get_json(silent=True) or {}
        message = str(data.get("message", ""))[:chatbot.MAX_MESSAGE_LEN]
        uni = university_info.localized(lang())
        ctx = {"schedule": schedule_info(), "services": repo.services_overview(db(), now()),
               "contacts": {"main": uni["contacts"]["main_building"],
                            "b5": uni["building5"]["address"],
                            "phone": uni["contacts"]["phone"],
                            "admission": uni["contacts"]["admission_phone"],
                            "email": uni["contacts"]["email"]}}
        result = chatbot.answer(message, lang(), ctx)
        return jsonify(reply=result["reply"], suggestions=result["suggestions"])



def _register_board_routes(app: Flask) -> None:
    @app.get("/board")
    def board():
        return render_template("board.html", data=repo.board_data(db(), now()))

    @app.get("/api/board")
    def api_board():
        return jsonify(repo.board_data(db(), now()))


# ---------------------------------------------------------------------------
# Тіркелу, кіру, шығу, профиль
# ---------------------------------------------------------------------------
def _register_auth_routes(app: Flask) -> None:

    @app.route("/register", methods=["GET", "POST"])
    def register():
        # Өзі тек студент тіркеледі; декан мен орынбасардың аккаунтын администратор ашады.
        kind = ql.STUDENT
        form = request.form if request.method == "POST" else {}
        if request.method == "POST":
            reg, errors = ql.validate_registration(
                kind, form.get("full_name"), form.get("password"), form.get("password2"),
                form.get("student_id"), form.get("group_name"), form.get("username"))
            if not errors and rate_limited("register", app.config["RATE_LIMIT"]):
                errors = ["err_rate"]
            if not errors:
                try:
                    repo.register(db(), reg, now())
                    flash("msg_registered_student", "ok")
                    return redirect(url_for("login"))
                except ql.QueueError as e:
                    errors = [e.code]
            for err in errors:
                flash(err, "error")
        return render_template("register.html", form=form)



def _register_login_routes(app: Flask) -> None:
    @app.route("/login", methods=["GET", "POST"])
    def login():
        # Барлығы бір формадан кіреді: логин (студентте — ЖСН) және құпиясөз.
        if request.method == "POST":
            if rate_limited("login", app.config["LOGIN_LIMIT"]):
                flash("err_rate", "error")
                return render_template("login.html"), 429
            user, err = repo.authenticate(db(), request.form.get("username"),
                                          request.form.get("password"))
            if err:
                if not app.config["TESTING"]:
                    time.sleep(0.3)  # құпиясөзді теріп табуды баяулату
                flash(err, "error")
            else:
                keep_lang = session.get("lang")
                session.clear()  # session fixation-нан қорғау
                if keep_lang:
                    session["lang"] = keep_lang
                session["user_id"] = user["id"]
                if user["role"] in ql.STAFF_ROLES:
                    repo.set_on_duty(db(), user["id"], True)
                repo.log(db(), user["id"], "login", user["role"], now())
                default = url_for(ROLE_HOME[user["role"]])
                return redirect(safe_next(request.form.get("next"), default))
        return render_template("login.html")



def _register_logout_routes(app: Flask) -> None:
    @app.post("/logout")
    def logout():
        user = current_user()
        if user is not None:
            repo.set_on_duty(db(), user["id"], False)
        keep_lang = session.get("lang")
        session.clear()
        if keep_lang:
            session["lang"] = keep_lang
        flash("msg_logged_out", "ok")
        return redirect(url_for("index"))



def _register_profile_routes(app: Flask) -> None:
    @app.route("/profile", methods=["GET", "POST"])
    @role_required(*ql.ROLES)
    def profile():
        user = current_user()
        if request.method == "POST":
            f = request.form
            try:
                if f.get("action") == "info":
                    data = ql.validate_profile(f.get("phone"), f.get("gender"), f.get("email"))
                    # Аты-жөнін администратор мен студент өзі өзгертеді, тобын — студент.
                    # Өріс жіберілмесе, бұрынғы мәні сақталады.
                    if user["role"] in (ql.ADMIN, ql.STUDENT) and "full_name" in f:
                        data["full_name"] = ql.validate_full_name(f.get("full_name"))
                    if user["role"] == ql.STUDENT and "group_name" in f:
                        data["group_name"] = ql.validate_group(f.get("group_name"))
                    repo.update_profile(db(), user["id"], data, now())
                    flash("msg_profile_saved", "ok")
                else:
                    repo.change_password(db(), user["id"], f.get("old_password"),
                                         f.get("password"), f.get("password2"), now())
                    flash("msg_password_changed", "ok")
                return redirect(url_for("profile"))
            except ql.QueueError as e:
                flash_error(e)
        sids = repo.user_service_ids(db(), user["id"])
        services = [s for s in repo.list_services(db(), False) if s["id"] in sids]
        return render_template("profile.html", services=services, form=request.form)



def _register_avatar_routes(app: Flask) -> None:
    @app.post("/profile/avatar")
    @role_required(*ql.ROLES)
    def profile_avatar():
        """Профиль суретін жүктеу (JPG, PNG, WEBP; 2 МБ дейін) немесе өшіру."""
        user = current_user()
        folder = avatar_dir()
        if request.form.get("action") == "delete":
            old = repo.set_avatar(db(), user["id"], "")
            _remove_avatar(folder, old)
            flash("msg_avatar_deleted", "ok")
            return redirect(url_for("profile"))
        file = request.files.get("avatar")
        data = file.read(AVATAR_MAX_BYTES + 1) if file else b""
        try:
            if not data:
                raise ql.QueueError("err_avatar_type")
            if len(data) > AVATAR_MAX_BYTES:
                raise ql.QueueError("err_avatar_size")
            ext = ql.detect_image_type(data)  # файл атауына емес, мазмұнына қараймыз
            name = f"u{user['id']}_{secrets.token_hex(8)}.{ext}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
            _remove_avatar(folder, repo.set_avatar(db(), user["id"], name))
            flash("msg_avatar_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return redirect(url_for("profile"))



def _register_avatar_view_routes(app: Flask) -> None:
    @app.get("/avatar/<int:user_id>")
    def avatar(user_id):
        """Профиль суреті: иесіне және деканат қызметкерлеріне ғана көрінеді."""
        viewer = current_user()
        if viewer is None or (viewer["id"] != user_id and viewer["role"] not in ql.STAFF_ROLES):
            abort(404)
        target = repo.get_user(db(), user_id)
        if target is None or not target["avatar"]:
            abort(404)
        resp = send_from_directory(avatar_dir(), target["avatar"], max_age=0)
        resp.headers["Cache-Control"] = "private, no-cache"
        return resp


def avatar_dir() -> Path:
    """Профиль суреттері дерекқормен бір қалтада (instance/avatars) — GitHub-қа түспейді."""
    return Path(current_app.config["DATABASE"]).parent / "avatars"


def _remove_avatar(folder: Path, name: str) -> None:
    if name and "/" not in name and "\\" not in name:
        (folder / name).unlink(missing_ok=True)


def ql_minutes(value) -> str:
    """4.0 -> '4', 2.5 -> '2.5' (минутты әдемі көрсету үшін)."""
    return f"{float(value):g}"


# ---------------------------------------------------------------------------
# Студент кабинеті
# ---------------------------------------------------------------------------
def _register_student_routes(app: Flask) -> None:

    @app.get("/student")
    @role_required(ql.STUDENT)
    def student_cabinet():
        user = current_user()
        tickets = repo.user_tickets(db(), user["id"])
        today = now().strftime("%Y-%m-%d")
        is_active = lambda tk: tk["day"] == today and tk["status"] in ql.ACTIVE_STATUSES
        active = [dict(tk, view=_ticket_view(tk)) for tk in tickets if is_active(tk)]
        history = [tk for tk in tickets if not is_active(tk)]
        return render_template(
            "student.html", services=repo.services_overview(db(), now()),
            active=active, history=history,
            is_open=open_now())

    @app.get("/api/student/tickets")
    @role_required(ql.STUDENT)
    def api_student_tickets():
        """Студент кабинеті үшін: өз талондарының күйлері (өзгерсе, бет жаңарады)."""
        rows = repo.user_tickets(db(), current_user()["id"])
        sig = ",".join(f"{r['id']}:{r['status']}:{r['window_no'] or ''}" for r in rows)
        queue = ",".join(str(repo.people_ahead(db(), r)) for r in rows if r["status"] == ql.WAITING)
        return jsonify(signature=sig + "|" + queue)



def _register_student_ticket_routes(app: Flask) -> None:
    @app.post("/student/ticket")
    @role_required(ql.STUDENT)
    def student_take_ticket():
        if rate_limited("ticket", app.config["RATE_LIMIT"]):
            flash("err_rate", "error")
            return redirect(url_for("student_cabinet"))
        try:
            ticket = repo.create_ticket(db(), current_user(), request.form.get("service_id"),
                                        now(), check_hours=app.config["CHECK_HOURS"])
            return redirect(url_for("ticket_page", token=ticket["token"]))
        except ql.QueueError as e:
            flash_error(e)
        return redirect(url_for("student_cabinet"))

    @app.post("/student/ticket/<int:ticket_id>/cancel")
    @role_required(ql.STUDENT)
    def student_cancel(ticket_id):
        try:
            repo.cancel_ticket(db(), ticket_id, current_user()["id"], now())
            flash("msg_cancelled", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return redirect(safe_next(request.form.get("next"), url_for("student_cabinet")))


# ---------------------------------------------------------------------------
# Деканат панелі (әкімші де кіре алады)
# ---------------------------------------------------------------------------
def _register_dekanat_routes(app: Flask) -> None:

    @app.get("/dekanat")
    @role_required(*ql.STAFF_ROLES)
    def dekanat_panel():
        conn = db()
        op = current_user()
        sids = repo.user_service_ids(conn, op["id"])
        services = [s for s in repo.list_services(conn) if s["id"] in sids]
        return render_template("operator.html", op=op, services=services,
                               current=repo.current_ticket(conn, op["id"]),
                               waiting=repo.waiting_for_services(conn, sids, now()),
                               stats=repo.stats_today(conn, now()))

    @app.post("/dekanat/next")
    @role_required(*ql.STAFF_ROLES)
    def dekanat_next():
        try:
            ticket = repo.call_next(db(), current_user()["id"], now())
            flash("msg_called" if ticket else "queue_empty", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return redirect(url_for("dekanat_panel"))



def _register_dekanat_action_routes(app: Flask) -> None:
    @app.post("/dekanat/ticket/<int:ticket_id>/<action>")
    @role_required(*ql.STAFF_ROLES)
    def dekanat_action(ticket_id, action):
        mapping = {"done": ql.DONE, "no_show": ql.NO_SHOW, "return": ql.WAITING}
        if action != "recall" and action not in mapping:
            abort(404)
        try:
            if action == "recall":
                repo.recall_ticket(db(), current_user()["id"], ticket_id)
            else:
                repo.finish_ticket(db(), current_user()["id"], ticket_id, mapping[action], now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return redirect(url_for("dekanat_panel"))

    @app.post("/dekanat/break")
    @role_required(*ql.STAFF_ROLES)
    def dekanat_break():
        """Қызметкердің жеке үзілісі: басталады не аяқталады."""
        user = current_user()
        try:
            repo.set_break(db(), user["id"], not user["on_break"], now())
            flash("msg_break_on" if not user["on_break"] else "msg_break_off", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return redirect(url_for("dekanat_panel"))




def _register_staff_api_routes(app: Flask) -> None:
    @app.get("/api/staff/queue")
    @role_required(*ql.STAFF_ROLES)
    def api_staff_queue():
        """Деканат панелі үшін: күтудегілер, ағымдағы студент, статистика (бетті жаңартпай)."""
        conn, op = db(), current_user()
        sids = repo.user_service_ids(conn, op["id"])
        waiting = [{"number": w["number"], "full_name": w["full_name"], "group_name": w["group_name"],
                    "priority": bool(w["priority"]), "time": w["created_at"][11:16], "code": w["code"]}
                   for w in repo.waiting_for_services(conn, sids, now())]
        current = repo.current_ticket(conn, op["id"])
        return jsonify(waiting=waiting, stats=repo.stats_today(conn, now()),
                       current=current["number"] if current else None,
                       on_break=bool(op["on_break"]))


# ---------------------------------------------------------------------------
# Әкімші панелі (декан және декан орынбасары)
# ---------------------------------------------------------------------------
ADMIN_TABS = ("users", "schedule", "calendar", "services", "tickets", "reports")


def _registration_from_form(f) -> tuple:
    """Әкімші панеліндегі «Жаңа аккаунт» формасын тексереді: (reg, errors)."""
    role = f.get("role")
    if role == ql.STUDENT:
        return ql.validate_registration(ql.STUDENT, f.get("full_name"), f.get("password"), None,
                                        f.get("student_id"), f.get("group_name"))
    reg, errors = ql.validate_registration(ql.DEKANAT, f.get("full_name"), f.get("password"),
                                           None, username=f.get("username"))
    if reg and role in ql.STAFF_ROLES:
        reg.role = role
    elif reg:
        errors = ["err_role"]
    return reg, errors


def back(tab: str):
    """Басқару панелінің берілген қойындысына қайтару."""
    return redirect(url_for("admin_panel", tab=tab))


def _admin_lists(conn, role_filter: str | None, q: str) -> tuple:
    """Іздеу сұранысы бойынша сүзілген пайдаланушылар (қызметтерімен) және бүгінгі талондар."""
    users = [u for u in repo.list_users(conn, role_filter)
             if ql.matches(q, u["full_name"], u["username"], u["group_name"])]
    user_services = {u["id"]: repo.user_service_ids(conn, u["id"]) for u in users}
    tickets = [tk for tk in repo.tickets_for_day(conn, now())
               if ql.matches(q, tk["number"], tk["full_name"], tk["group_name"])]
    return users, user_services, tickets


def _register_admin_routes(app: Flask) -> None:

    @app.get("/admin")
    @role_required(*ql.MANAGER_ROLES)
    def admin_panel():
        conn = db()
        tab = request.args.get("tab", "users")
        if tab not in ADMIN_TABS:
            tab = "users"
        role_filter = request.args.get("role")
        if role_filter not in ql.ROLES:
            role_filter = None
        q = request.args.get("q", "").strip()
        users, user_services, tickets = _admin_lists(conn, role_filter, q)
        return render_template(
            "admin.html", tab=tab, role_filter=role_filter, users=users, q=q,
            user_services=user_services, pending=repo.count_pending(conn),
            services=repo.list_services(conn, active_only=False),
            tickets=tickets, statuses=repo.ALL_STATUSES, report=_report_context(tab),
            stats=repo.stats_today(conn, now()),
            sched_form=ql.schedule_to_dict(schedule()),
            announcements=repo.list_announcements(conn, now()),
            day_overrides=repo.list_overrides(conn, now().strftime("%Y-%m-%d")),
            today=now().strftime("%Y-%m-%d"),
            can_manage=lambda target_role: ql.can_manage_user(current_user()["role"], target_role),
            assignable_roles=[r for r in ql.ROLES
                              if ql.can_manage_user(current_user()["role"], r, r)])



def _report_period() -> tuple[date, date]:
    """Сұраудағы есеп кезеңі; қате болса — хабар шығарып, соңғы 7 күн."""
    try:
        return ql.parse_period(request.args.get("start", ""), request.args.get("end", ""), now().date())
    except ql.QueueError as e:
        flash_error(e)
        return ql.parse_period("", "", now().date())


def _report_context(tab: str) -> dict | None:
    if tab != "reports":
        return None
    start, end = _report_period()
    rows = repo.tickets_between(db(), start.isoformat(), end.isoformat())
    return dict(ql.summarize_tickets(rows, "name_" + lang()), start=start.isoformat(), end=end.isoformat())


def _csv_minutes(a, b):
    m = ql.minutes_between(a, b)
    return "" if m is None else round(m, 1)


def _report_csv(rows: list[dict]) -> str:
    """Excel ашатын CSV: UTF-8 BOM, «;» бөлгіш."""
    import csv
    import io
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf, delimiter=";")
    w.writerow([t(k) for k in ("date", "board_ticket", "service", "status", "student", "group", "window",
                               "created", "rep_called", "rep_finished", "rep_wait", "rep_service_time")])
    for r in rows:
        w.writerow([r["day"], r["number"], r["name_" + lang()], t("st_" + r["status"]), r["full_name"],
                    r["group_name"], r["window_no"] or "", r["created_at"][11:16],
                    (r["called_at"] or "")[11:16], (r["finished_at"] or "")[11:16],
                    _csv_minutes(r["created_at"], r["called_at"]),
                    _csv_minutes(r["called_at"], r["finished_at"])])
    return buf.getvalue()


def _register_report_routes(app: Flask) -> None:
    @app.get("/admin/reports.csv")
    @role_required(*ql.MANAGER_ROLES)
    def admin_reports_csv():
        start, end = _report_period()
        rows = repo.tickets_between(db(), start.isoformat(), end.isoformat())
        name = f"dekanat-report-{start:%Y%m%d}-{end:%Y%m%d}.csv"
        return Response(_report_csv(rows), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/admin/backup")
    @role_required(ql.ADMIN)
    def admin_backup():
        """Дерекқордың резервтік көшірмесін жүктеу (тек администратор)."""
        repo.log(db(), current_user()["id"], "backup", "", now())
        name = f"dekanat-{now():%Y%m%d-%H%M}.db"
        return Response(repo.backup_bytes(db()), mimetype="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _register_manage_api_routes(app: Flask) -> None:
    @app.get("/api/manage/changes")
    @role_required(*ql.MANAGER_ROLES)
    def api_manage_changes():
        """Басқару панелі үшін: бүгінгі талондар мен растауды күтетіндердің «қолтаңбасы»."""
        conn = db()
        rows = conn.execute("SELECT id, status FROM tickets WHERE day=? ORDER BY id",
                            (now().strftime("%Y-%m-%d"),)).fetchall()
        sig = ",".join(f"{r['id']}:{r['status']}" for r in rows) + f"|p{repo.count_pending(conn)}"
        return jsonify(signature=sig, tickets=len(rows), pending=repo.count_pending(conn))



def _register_admin_user_routes(app: Flask) -> None:
    @app.post("/admin/users/new")
    @role_required(*ql.MANAGER_ROLES)
    def admin_user_new():
        f = request.form
        try:
            reg, errors = _registration_from_form(f)
            if not errors and not ql.can_manage_user(current_user()["role"], reg.role, reg.role):
                errors = ["err_forbidden"]
            if errors:
                for err in errors:
                    flash(err, "error")
                return back("users")
            window = f.get("window_no") or None
            repo.create_user(db(), reg.username, reg.password, reg.full_name, reg.role,
                                   now=now(), student_id=reg.student_id,
                                   group_name=reg.group_name,
                                   window_no=int(window) if window and window.isdigit() else None)
            repo.log(db(), current_user()["id"], "create_user", f"{reg.role}:{reg.username}", now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("users")



def _register_admin_user_action_routes(app: Flask) -> None:
    @app.post("/admin/users/<int:user_id>/<action>")
    @role_required(*ql.MANAGER_ROLES)
    def admin_user_action(user_id, action):
        conn, admin_id, f = db(), current_user()["id"], request.form
        try:
            if action == "activate":
                repo.admin_set_active(conn, admin_id, user_id, True, now())
            elif action == "block":
                repo.admin_set_active(conn, admin_id, user_id, False, now())
            elif action == "role":
                repo.admin_set_role(conn, admin_id, user_id, f.get("role"), now())
            elif action == "password":
                repo.admin_reset_password(conn, admin_id, user_id, f.get("password"), now())
            elif action == "staff":
                repo.admin_update_staff(conn, admin_id, user_id, f.get("window_no"),
                                        f.getlist("services"), now())
            elif action == "delete":
                repo.admin_delete_user(conn, admin_id, user_id, now())
            else:
                abort(404)
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("users")



def _register_admin_schedule_routes(app: Flask) -> None:
    @app.post("/admin/schedule")
    @role_required(*ql.MANAGER_ROLES)
    def admin_schedule_save():
        f = request.form
        try:
            # Қысқа үзілістер алынып тасталды: кестеде тек жұмыс уақыты мен түскі үзіліс
            new = ql.build_schedule(f.get("open_at"), f.get("close_at"), f.get("lunch_from"),
                                    f.get("lunch_to"), "", f.getlist("workdays"))
            repo.save_schedule(db(), current_user()["id"], new, now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("schedule")



def _register_admin_announcement_routes(app: Flask) -> None:
    @app.post("/admin/announcements/new")
    @role_required(*ql.MANAGER_ROLES)
    def admin_announcement_new():
        f = request.form
        try:
            a = ql.build_announcement(f.get("text"), f.get("start_day"), f.get("end_day"), now().date())
            repo.add_announcement(db(), current_user()["id"], a, now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("calendar")

    @app.post("/admin/announcements/<int:announcement_id>/delete")
    @role_required(*ql.MANAGER_ROLES)
    def admin_announcement_delete(announcement_id):
        try:
            repo.delete_announcement(db(), current_user()["id"], announcement_id, now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("calendar")



def _register_admin_day_routes(app: Flask) -> None:
    @app.post("/admin/days/save")
    @role_required(*ql.MANAGER_ROLES)
    def admin_day_save():
        f = request.form
        try:
            o = ql.build_override(f.get("day"), f.get("kind"), f.get("open_at"), f.get("close_at"),
                                  f.get("note"))
            repo.save_override(db(), current_user()["id"], o, now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("calendar")

    @app.post("/admin/days/<day>/delete")
    @role_required(*ql.MANAGER_ROLES)
    def admin_day_delete(day):
        try:
            date.fromisoformat(day)
            repo.delete_override(db(), current_user()["id"], day, now())
            flash("msg_saved", "ok")
        except ValueError:
            flash("err_date", "error")
        except ql.QueueError as e:
            flash_error(e)
        return back("calendar")



def _register_admin_service_routes(app: Flask) -> None:
    @app.post("/admin/services/save")
    @role_required(*ql.MANAGER_ROLES)
    def admin_service_save():
        f = request.form
        sid = f.get("service_id")
        try:
            repo.admin_save_service(db(), current_user()["id"],
                                    int(sid) if sid and sid.isdigit() else None,
                                    f.get("code"), f.get("name_kk"), f.get("name_ru"),
                                    f.get("avg_minutes"), f.get("is_active") == "1", now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("services")



def _register_admin_ticket_routes(app: Flask) -> None:
    @app.post("/admin/tickets/<int:ticket_id>/<action>")
    @role_required(*ql.MANAGER_ROLES)
    def admin_ticket_action(ticket_id, action):
        try:
            if action == "status":
                repo.admin_set_ticket_status(db(), current_user()["id"], ticket_id,
                                             request.form.get("status"), now())
            elif action == "delete":
                repo.admin_delete_ticket(db(), current_user()["id"], ticket_id, now())
            else:
                abort(404)
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("tickets")


def _register_cli(app: Flask) -> None:
    @app.cli.command("set-password")
    @click.argument("username")
    def set_password_command(username):
        """Құпиясөзді консольден қалпына келтіру: flask --app app.web set-password admin

        Декан құпиясөзін ұмытса, хостинг консолінде орындалады. Құпиясөз экранда көрінбейді.
        """
        password = click.prompt("Жаңа құпиясөз / Новый пароль", hide_input=True,
                                confirmation_prompt=True)
        conn = repo.connect(app.config["DATABASE"])
        try:
            repo.force_set_password(conn, username, password, app.config["NOW"]())
            click.echo(f"OK: {username}")
        except ql.QueueError as e:
            raise click.ClickException(translate(e.code, "kk"))
        finally:
            conn.close()


def _register_teardown(app: Flask) -> None:
    @app.teardown_appcontext
    def close_db(_exc):
        request_conn = g.pop("db_conn", None)
        if request_conn is not None:
            request_conn.close()


# Барлық маршрут топтары: create_app() оларды осы ретпен тіркейді.
ROUTE_GROUPS = (
    _register_teardown,
    _register_helpers,
    _register_public_routes,
    _register_auth_routes,
    _register_student_routes,
    _register_dekanat_routes,
    _register_admin_routes,
    _register_security_headers,
    _register_error_handlers,
    _register_ticket_routes,
    _register_chat_routes,
    _register_board_routes,
    _register_login_routes,
    _register_logout_routes,
    _register_profile_routes,
    _register_avatar_routes,
    _register_student_ticket_routes,
    _register_dekanat_action_routes,
    _register_staff_api_routes,
    _register_manage_api_routes,
    _register_admin_user_routes,
    _register_admin_user_action_routes,
    _register_admin_schedule_routes,
    _register_admin_day_routes,
    _register_admin_service_routes,
    _register_admin_ticket_routes,
    _register_avatar_view_routes,
    _register_admin_announcement_routes,
    _register_report_routes,
    _register_cli,
)


def _safe_console() -> None:
    """Windows консолі (cp1251/cp866) қазақ әріптерін (ұ, қ, ң...) шығара алмай құламауы үшін."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _safe_console()
    parser = argparse.ArgumentParser(description="Деканаттың электрондық кезегі")
    parser.add_argument("--lan", action="store_true",
                        help="Сайтты Wi-Fi желісіне ашу (телефоннан кіру үшін)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    args = parser.parse_args()

    host = "0.0.0.0" if args.lan else os.environ.get("HOST", "127.0.0.1")
    port = args.port
    config = {}
    print(f" * Деканат кезегі (осы компьютерде): http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        ips = local_ips()
        if ips:
            config["PUBLIC_URL"] = os.environ.get("PUBLIC_URL") or f"http://{ips[0]}:{port}/"
            print(" * Телефоннан ашу (телефон осы Wi-Fi желісінде болуы керек):")
            for ip in ips:
                print(f"     http://{ip}:{port}")
            print(" * Windows брандмауэрі сұраса, «Рұқсат беру» батырмасын басыңыз.")
        else:
            print(" ! Желі мекенжайы табылмады: компьютер Wi-Fi-ға қосылғанын тексеріңіз.")
    app = create_app(config)
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1", threaded=True)


if __name__ == "__main__":
    main()
