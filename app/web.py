"""
Қорқыт Ата атындағы Қызылорда университеті — деканаттың электрондық кезегі.
Веб-интерфейс (Flask). Іске қосу: flask --app app.web run  немесе  python run.py

Үш рөл:
  student  — тіркеледі, кабинетте талон алады, өз талондарын көреді
  dekanat  — деканат қызметкері: студенттерді шақырады (әкімші растағаннан кейін)
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
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for

from . import chatbot, university_info
from . import db as repo
from . import service as ql
from .i18n import DEFAULT_LANG, LANGUAGES, translate

BASE_DIR = Path(__file__).resolve().parent.parent  # жобаның түбірі
ROLE_HOME = {ql.STUDENT: "student_cabinet", ql.DEKANAT: "dekanat_panel",
             ql.DEPUTY: "admin_panel", ql.ADMIN: "admin_panel"}
CHAT_LIMIT = 30  # бір IP-ден минутына неше чат хабарламасы


# ---------------------------------------------------------------------------
# Қолданба фабрикасы (тесттерде басқа баптаулармен жасауға болады)
# ---------------------------------------------------------------------------
def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=str(BASE_DIR / "instance" / "dekanat.db"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or _load_or_create_secret(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
        CHECK_HOURS=os.environ.get("QUEUE_DEMO", "1") != "1",  # демо: уақыт тексерілмейді
        RATE_LIMIT=5,            # бір IP-ден минутына неше талон / тіркелу
        LOGIN_LIMIT=10,          # бір IP-ден минутына неше кіру әрекеті
        NOW=datetime.now,        # тесттерде уақытты ауыстыру үшін
        PUBLIC_URL=os.environ.get("PUBLIC_URL", ""),  # QR-кодтағы мекенжай (телефондар үшін)
        SHOW_DEMO_ACCOUNTS=os.environ.get("SHOW_DEMO_ACCOUNTS", "1") != "0",  # хостингте 0
        TESTING=False,
    )
    if config:
        app.config.update(config)

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

    @app.teardown_appcontext
    def close_db(_exc):
        request_conn = g.pop("db_conn", None)
        if request_conn is not None:
            request_conn.close()

    _register_helpers(app)
    _register_public_routes(app)
    _register_auth_routes(app)
    _register_student_routes(app)
    _register_dekanat_routes(app)
    _register_admin_routes(app)
    return app


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


def open_now() -> bool:
    """Талон беруге бола ма? Демо-режимде уақыт тексерілмейді."""
    return ql.is_open(now(), schedule()) or not current_app.config["CHECK_HOURS"]


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
    pause = ql.current_pause(now(), s)
    if pause and now().weekday() in s.workdays:
        status = pause
    else:
        status = "open" if ql.is_open(now(), s) else "closed"
    return {"days": days_text, "hours": f"{hhmm(s.open_at)}–{hhmm(s.close_at)}",
            "lunch": f"{hhmm(s.lunch_from)}–{hhmm(s.lunch_to)}" if s.lunch_from else "",
            "breaks": [f"{hhmm(a)}–{hhmm(b)}" for a, b in s.breaks], "status": status}


def _register_helpers(app: Flask) -> None:
    @app.context_processor
    def inject():
        user = current_user()
        return {"t": t, "lang": lang(), "languages": LANGUAGES, "csrf_token": csrf_token,
                "public_url": public_url,
                "demo": not app.config["CHECK_HOURS"], "user": user,
                "show_demo_accounts": app.config["SHOW_DEMO_ACCOUNTS"],
                "role_home": ROLE_HOME, "roles": ql.ROLES, "sched": schedule_info,
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

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", message=t("err_404")), 404


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
            is_open=open_now())

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
        kind = request.values.get("kind", ql.STUDENT)
        if kind not in ql.ROLES:
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
                    if kind == ql.STUDENT:
                        flash("msg_registered_student", "ok")
                    else:
                        flash("msg_registered_staff", "ok")
                    return redirect(url_for("login", role=kind))
                except ql.QueueError as e:
                    errors = [e.code]
            for err in errors:
                flash(err, "error")
        return render_template("register.html", kind=kind, form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        role = request.values.get("role", ql.STUDENT)
        if role not in ql.ROLES:
            role = ql.STUDENT
        if request.method == "POST":
            if rate_limited("login", app.config["LOGIN_LIMIT"]):
                flash("err_rate", "error")
                return render_template("login.html", role=role), 429
            user, err = repo.authenticate(db(), request.form.get("username"),
                                          request.form.get("password"), role)
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
        return render_template("login.html", role=role)

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

    @app.route("/profile", methods=["GET", "POST"])
    @role_required(*ql.ROLES)
    def profile():
        user = current_user()
        if request.method == "POST":
            try:
                repo.change_password(db(), user["id"], request.form.get("old_password"),
                                     request.form.get("password"),
                                     request.form.get("password2"), now())
                flash("msg_password_changed", "ok")
                return redirect(url_for("profile"))
            except ql.QueueError as e:
                flash_error(e)
        sids = repo.user_service_ids(db(), user["id"])
        services = [s for s in repo.list_services(db(), False) if s["id"] in sids]
        return render_template("profile.html", services=services)


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

    @app.post("/student/ticket")
    @role_required(ql.STUDENT)
    def student_take_ticket():
        if rate_limited("ticket", app.config["RATE_LIMIT"]):
            flash("err_rate", "error")
            return redirect(url_for("student_cabinet"))
        try:
            ticket = repo.create_ticket(db(), current_user(), request.form.get("service_id"),
                                        now(), priority=request.form.get("priority") == "1",
                                        check_hours=app.config["CHECK_HOURS"])
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
ADMIN_TABS = ("users", "schedule", "services", "tickets", "audit")


def _register_admin_routes(app: Flask) -> None:

    def back(tab: str):
        return redirect(url_for("admin_panel", tab=tab))

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
        users = repo.list_users(conn, role_filter)
        user_services = {u["id"]: repo.user_service_ids(conn, u["id"]) for u in users}
        return render_template(
            "admin.html", tab=tab, role_filter=role_filter, users=users,
            user_services=user_services, pending=repo.count_pending(conn),
            services=repo.list_services(conn, active_only=False),
            tickets=repo.tickets_for_day(conn, now()), statuses=repo.ALL_STATUSES,
            audit=repo.list_audit(conn), stats=repo.stats_today(conn, now()),
            sched_form=ql.schedule_to_dict(schedule()),
            can_manage=lambda target_role: ql.can_manage_user(current_user()["role"], target_role),
            assignable_roles=[r for r in ql.ROLES
                              if ql.can_manage_user(current_user()["role"], r, r)])

    @app.get("/api/manage/changes")
    @role_required(*ql.MANAGER_ROLES)
    def api_manage_changes():
        """Басқару панелі үшін: бүгінгі талондар мен растауды күтетіндердің «қолтаңбасы»."""
        conn = db()
        rows = conn.execute("SELECT id, status FROM tickets WHERE day=? ORDER BY id",
                            (now().strftime("%Y-%m-%d"),)).fetchall()
        sig = ",".join(f"{r['id']}:{r['status']}" for r in rows) + f"|p{repo.count_pending(conn)}"
        return jsonify(signature=sig, tickets=len(rows), pending=repo.count_pending(conn))

    @app.post("/admin/users/new")
    @role_required(*ql.MANAGER_ROLES)
    def admin_user_new():
        f = request.form
        role = f.get("role")
        try:
            if role == ql.STUDENT:
                reg, errors = ql.validate_registration(
                    ql.STUDENT, f.get("full_name"), f.get("password"), None,
                    f.get("student_id"), f.get("group_name"))
            else:
                reg, errors = ql.validate_registration(
                    ql.DEKANAT, f.get("full_name"), f.get("password"), None,
                    username=f.get("username"))
                if reg and role in ql.STAFF_ROLES:
                    reg.role = role
                elif reg:
                    errors = ["err_role"]
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

    @app.post("/admin/schedule")
    @role_required(*ql.MANAGER_ROLES)
    def admin_schedule_save():
        f = request.form
        try:
            new = ql.build_schedule(f.get("open_at"), f.get("close_at"), f.get("lunch_from"),
                                    f.get("lunch_to"), f.get("breaks"), f.getlist("workdays"))
            repo.save_schedule(db(), current_user()["id"], new, now())
            flash("msg_saved", "ok")
        except ql.QueueError as e:
            flash_error(e)
        return back("schedule")

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
