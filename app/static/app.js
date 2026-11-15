// Деканаттың электрондық кезегі — клиенттік скрипт.
// CSP саясатына сай барлық JS осы файлда (inline-скрипттер жоқ).
(function () {
  "use strict";
  const body = document.body;
  const page = body.dataset.page;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // ---------- Телефондағы мәзір ----------
  const toggle = document.querySelector(".nav-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      const open = body.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ---------- Растауды талап ететін формалар (бас тарту, өшіру) ----------
  // window.confirm() кейбір браузерлерде (Instagram/Telegram ішіндегі браузер, «диалогтарға
  // тыйым салу» белгіленген Chrome) бірден «Болдырмау» қайтарады — сонда өшіру мүлде орындалмайды.
  // Сондықтан растау беттің өзінде көрсетіледі.
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.confirmed === "1") return;
      e.preventDefault();
      if (f.confirmBar && f.confirmBar.isConnected) return;
      const bar = document.createElement("div");
      bar.className = "confirm-bar";
      bar.setAttribute("role", "alertdialog");
      const text = document.createElement("span");
      text.textContent = f.dataset.confirm;
      const yes = document.createElement("button");
      yes.type = "button";
      yes.className = "btn btn-danger";
      yes.textContent = body.dataset.yes || "OK";
      const no = document.createElement("button");
      no.type = "button";
      no.className = "btn";
      no.textContent = body.dataset.no || "×";
      yes.addEventListener("click", function () {
        f.dataset.confirmed = "1";
        bar.remove();
        f.submit();
      });
      no.addEventListener("click", function () { bar.remove(); });
      bar.append(text, yes, no);
      // Форма жолдың ішінде (мысалы, хабарландыру жанындағы «Өшіру») тұрса, растау жолақшасы
      // тар формаға сыймай, беттен шығып кетеді. Ондай кезде оны жолдың астына, толық енімен қоямыз.
      const parent = f.parentElement;
      const style = parent ? window.getComputedStyle(parent) : null;
      if (style && style.display.indexOf("flex") >= 0 && style.flexDirection.indexOf("row") === 0) {
        parent.classList.add("has-confirm");
        bar.classList.add("confirm-bar-wide");
        f.after(bar);
        no.addEventListener("click", function () { parent.classList.remove("has-confirm"); });
      } else {
        f.appendChild(bar);
      }
      f.confirmBar = bar;
      yes.focus();
    });
  });

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      osc.connect(gain); gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      osc.start(); osc.stop(ctx.currentTime + 0.4);
    } catch (e) { /* дыбыс міндетті емес */ }
    if (navigator.vibrate) navigator.vibrate([300, 100, 300]);
  }

  function poll(url, handler, ms) {
    setInterval(function () {
      fetch(url, { headers: { "Accept": "application/json" }, cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { if (data) handler(data); })
        .catch(function () { /* желі уақытша жоқ — келесі жолы қайталаймыз */ });
    }, ms);
  }

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }

  // ---------- Талон беті ----------
  if (page === "ticket") {
    let lastStatus = null, lastRecall = null;
    poll(body.dataset.api, function (d) {
      const st = document.getElementById("t-status");
      st.textContent = d.status_text;
      st.className = "status status-" + d.status;
      document.getElementById("t-ahead").textContent = d.ahead;
      document.getElementById("t-estimate").textContent = d.estimate;
      document.getElementById("t-window").textContent = d.window || "";
      document.getElementById("called-box").hidden = d.status !== "called";
      document.getElementById("t-late").hidden = !d.late;
      document.getElementById("ticket-card").classList.toggle("is-called", d.status === "called");
      if (d.status === "called" && (lastStatus !== "called" || lastRecall !== d.recall)) beep();
      if (lastStatus && lastStatus !== d.status && ["done", "no_show", "cancelled"].indexOf(d.status) >= 0) {
        window.location.reload();
      }
      lastStatus = d.status; lastRecall = d.recall;
    }, 5000);
  }

  // ---------- Табло ----------
  if (page === "board") {
    const clock = document.getElementById("clock");
    function updateClock() { clock.textContent = new Date().toLocaleTimeString().slice(0, 5); }
    updateClock(); setInterval(updateClock, 10000);

    let lastTop = null;
    poll(body.dataset.api, function (d) {
      const called = document.getElementById("called-list");
      called.replaceChildren();
      if (!d.called.length) {
        const tr = el("tr"); const td = el("td", body.dataset.empty, "empty");
        td.colSpan = 2; tr.appendChild(td); called.appendChild(tr);
      }
      d.called.forEach(function (c, i) {
        const tr = el("tr", undefined, i === 0 ? "fresh" : "");
        tr.append(el("td", c.number), el("td", String(c.window_no)));
        called.appendChild(tr);
      });
      const top = d.called.length ? d.called[0].number + ":" + d.called[0].recall_count : null;
      if (top && lastTop !== null && top !== lastTop) beep();
      lastTop = top;

      const queue = document.getElementById("queue-list");
      const qd = d.queue || [];
      document.getElementById("queue-count").textContent = String(qd.length);
      queue.replaceChildren();
      if (!qd.length) {
        const tr = el("tr"); const td = el("td", body.dataset.queueEmpty, "empty");
        td.colSpan = 3; tr.appendChild(td); queue.appendChild(tr);
      }
      qd.forEach(function (q, i) {
        const tr = el("tr", undefined, i === 0 ? "next-up" : "");
        tr.append(el("td", String(q.pos)), el("td", q.number),
                  el("td", q["name_" + body.dataset.lang] || q.name_kk));
        queue.appendChild(tr);
      });

      const windows = document.getElementById("windows-list");
      windows.replaceChildren();
      (d.windows || []).forEach(function (w) {
        const li = el("li");
        li.append(el("span", body.dataset.window + " " + w.window_no),
                  el("span", w.on_break ? body.dataset.break : body.dataset.working,
                     w.on_break ? "state-break" : "state-open"));
        windows.appendChild(li);
      });
    }, 4000);
  }

  // Пайдаланушы бір нәрсе жазып не таңдап отырса, бетті жаңартпаймыз
  function userIsBusy() {
    const a = document.activeElement;
    const chatBox = document.getElementById("chat");
    return (a && ["INPUT", "SELECT", "TEXTAREA"].indexOf(a.tagName) >= 0) ||
      (chatBox && !chatBox.hidden) || document.querySelector("details[open]");
  }

  function showNewTicket(numbers) {
    const box = document.getElementById("new-ticket-alert");
    if (!box || !numbers.length) return;
    box.textContent = body.dataset.new.replace("{n}", numbers.join(", "));
    box.hidden = false;
    beep();
    clearTimeout(showNewTicket.timer);
    showNewTicket.timer = setTimeout(function () { box.hidden = true; }, 15000);
  }

  // ---------- Деканат панелі: жаңа талондар бетті жаңартпай пайда болады ----------
  if (page === "operator") {
    let known = null;
    poll(body.dataset.api, function (d) {
      const numbers = d.waiting.map(function (w) { return w.number; });
      if (known === null) {
        known = new Set(Array.from(document.querySelectorAll("#waiting-body tr")).map(function (tr) { return tr.dataset.number; }));
      }
      const fresh = numbers.filter(function (n) { return !known.has(n); });
      known = new Set(numbers);

      const tbody = document.getElementById("waiting-body");
      tbody.replaceChildren();
      d.waiting.forEach(function (w) {
        const tr = el("tr");
        tr.dataset.number = w.number;
        if (fresh.indexOf(w.number) >= 0) tr.className = "row-new";
        const c1 = el("td", w.number); c1.dataset.label = body.dataset.lTicket;
        if (w.priority) { c1.append(" ", el("span", body.dataset.priority, "tag tag-warn")); }
        const c2 = el("td", w.full_name); c2.dataset.label = body.dataset.lStudent;
        const c3 = el("td", w.group_name || "—"); c3.dataset.label = body.dataset.lGroup;
        const c4 = el("td", w.time); c4.dataset.label = body.dataset.lTime;
        tr.append(c1, c2, c3, c4);
        tbody.appendChild(tr);
      });
      document.getElementById("waiting-count").textContent = d.waiting.length;
      document.getElementById("waiting-table").hidden = d.waiting.length === 0;
      document.getElementById("waiting-empty").hidden = d.waiting.length > 0;
      Object.keys(d.stats).forEach(function (k) {
        const cell = document.getElementById("stat-" + k);
        if (cell) cell.textContent = d.stats[k];
      });
      showNewTicket(fresh);

      // Ағымдағы студент не үзіліс күйі басқа жерден өзгерсе — бетті жаңартамыз
      const changed = (d.current || "") !== body.dataset.current ||
        (d.on_break ? "1" : "0") !== body.dataset.onBreak;
      if (changed && !userIsBusy()) window.location.reload();
    }, 3000);
  }

  // ---------- Басқару панелі (декан, орынбасар): өзгеріс болса бет жаңарады ----------
  if (page === "manage") {
    let lastSig = null, lastCount = null;
    poll(body.dataset.api, function (d) {
      if (lastSig !== null && d.signature !== lastSig) {
        if (userIsBusy()) return;  // форманы толтырып жатса — кейінірек жаңартамыз
        if (lastCount !== null && d.tickets > lastCount) sessionStorageSafe("newTicketAlert", "1");
        window.location.reload();
        return;
      }
      lastSig = d.signature; lastCount = d.tickets;
    }, 4000);
    if (sessionStorageSafe("newTicketAlert") === "1") {
      sessionStorageSafe("newTicketAlert", "");
      const box = document.getElementById("new-ticket-alert");
      if (box) { box.textContent = body.dataset.new.replace("{n}", "+1"); box.hidden = false; beep(); }
    }
  }

  // ---------- Студент кабинеті: талон күйі өзгерсе бет жаңарады ----------
  if (page === "student") {
    let lastSig = null;
    poll(body.dataset.api, function (d) {
      if (lastSig !== null && d.signature !== lastSig && !userIsBusy()) {
        window.location.reload();
        return;
      }
      lastSig = d.signature;
    }, 4000);
  }

  function sessionStorageSafe(key, value) {
    try {
      if (value === undefined) return window.sessionStorage.getItem(key);
      window.sessionStorage.setItem(key, value);
    } catch (e) { return null; }
    return null;
  }

  // ---------- Көмекші-чат ----------
  const chat = document.getElementById("chat");
  if (chat) {
    const log = document.getElementById("chat-log");
    const input = document.getElementById("chat-input");
    const sugg = document.getElementById("chat-sugg");
    const openBtn = document.getElementById("chat-toggle");

    function add(text, mine) {
      log.appendChild(el("div", text, "chat-msg" + (mine ? " me" : "")));
      log.scrollTop = log.scrollHeight;
    }

    function showSuggestions(list) {
      sugg.replaceChildren();
      (list || []).forEach(function (q) {
        const b = el("button", q);
        b.type = "button";
        b.addEventListener("click", function () { send(q); });
        sugg.appendChild(b);
      });
    }

    function ask(text) {
      return fetch(chat.dataset.api, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ message: text })
      }).then(function (r) { return r.json(); });
    }

    function send(text) {
      text = (text || "").trim();
      if (!text) return;
      add(text, true);
      input.value = "";
      ask(text)
        .then(function (d) { add(d.reply || d.error || chat.dataset.error); showSuggestions(d.suggestions); })
        .catch(function () { add(chat.dataset.error); });
    }

    openBtn.addEventListener("click", function () {
      chat.hidden = false;
      openBtn.hidden = true;
      input.focus();
      if (!sugg.children.length) {
        ask("").then(function (d) { showSuggestions(d.suggestions); }).catch(function () {});
      }
    });
    document.getElementById("chat-close").addEventListener("click", function () {
      chat.hidden = true;
      openBtn.hidden = false;
    });
    document.getElementById("chat-form").addEventListener("submit", function (e) {
      e.preventDefault();
      send(input.value);
    });
  }

  // ---------- Құпиясөз беріктігі (серверлік ережемен бірдей: service.password_strength) ----------
  // weak — қызыл, medium — қызғылт сары (кіші + бас әріп + цифр),
  // strong — жасыл (тыныс белгісі + әріп + цифр).
  function strength(pw) {
    if (pw.length < 8) return "weak";
    const digit = /\d/.test(pw);
    const lower = /\p{Ll}/u.test(pw);
    const upper = /\p{Lu}/u.test(pw);
    const symbol = /[^\p{L}\p{N}\s]/u.test(pw);
    if (symbol && (lower || upper) && digit) return "strong";
    if (lower && upper && digit) return "medium";
    return "weak";
  }
  document.querySelectorAll("input[data-strength]").forEach(function (input) {
    const meter = document.getElementById(input.dataset.strength);
    if (!meter) return;
    const label = meter.querySelector(".pw-label");
    input.addEventListener("input", function () {
      const v = input.value;
      meter.hidden = v.length === 0;
      const level = strength(v);
      meter.className = "pw-meter pw-" + level;
      label.textContent = meter.dataset[level];
    });
  });

  // ---------- Профиль суреті: файлды таңдаған соң бірден жүктеу ----------
  document.querySelectorAll("input[data-autosubmit]").forEach(function (input) {
    input.addEventListener("change", function () {
      if (input.files && input.files.length) input.form.submit();
    });
  });

  // ---------- Ерекше күн формасы: «Демалыс» таңдалса, сағат өрістері керек емес ----------
  const dayKind = document.querySelector("#day-form select[name=kind]");
  if (dayKind) {
    const hours = document.getElementById("day-hours");
    const sync = function () { hours.hidden = dayKind.value !== "short"; };
    dayKind.addEventListener("change", sync);
    sync();
  }
})();
