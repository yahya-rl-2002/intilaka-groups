(() => {
  const ACTIONS = {
    in: {fr: "Arrivée", ar: "وصول", icon: "→", tone: "go"},
    break_start: {fr: "Début de pause", ar: "بداية الاستراحة", icon: "❚❚", tone: "pause"},
    break_end: {fr: "Fin de pause", ar: "نهاية الاستراحة", icon: "▶", tone: "go"},
    out: {fr: "Départ", ar: "مغادرة", icon: "←", tone: "stop"}
  };
  const STATES = {
    out: {fr: "Pas au bureau", ar: "خارج المكتب"},
    in: {fr: "Au bureau", ar: "في المكتب"},
    break: {fr: "En pause", ar: "في استراحة"}
  };
  const ERRORS = {
    office_network_required: "Le pointage fonctionne uniquement depuis le Wi-Fi du bureau. · التسجيل ممكن فقط من شبكة المكتب.",
    invalid_pin: "Code incorrect. · الرمز غير صحيح.",
    too_many_attempts: "Trop d’essais. Réessayez dans 15 minutes. · محاولات كثيرة، أعد المحاولة بعد 15 دقيقة.",
    invalid_sequence: "Action déjà enregistrée. · تم تسجيل هذا الإجراء مسبقاً."
  };
  const DEFAULT_ERROR = "Connexion impossible. Réessayez. · تعذر الاتصال، أعد المحاولة.";

  const $ = (selector) => document.querySelector(selector);
  const steps = ["stepNames", "stepPin", "stepActions", "stepDone"].map((id) => document.getElementById(id));
  let employee = null, pin = "", resetTimer = null, officeTimeZone = "Africa/Casablanca";

  function el(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    children.forEach((child) => node.append(child));
    return node;
  }
  function bilingual(fr, ar) {
    const arabic = el("bdi", "", ar); arabic.lang = "ar";
    return [fr, " · ", arabic];
  }
  function show(step) {
    steps.forEach((section) => { section.hidden = section.id !== step; });
    clearTimeout(resetTimer);
    if (step === "stepActions" || step === "stepDone") resetTimer = setTimeout(reset, step === "stepDone" ? 6000 : 60000);
  }
  function reset() { employee = null; pin = ""; renderDots(); show("stepNames"); loadEmployees(); }
  function formatMinutes(total) { return `${Math.floor(total / 60)}h${String(total % 60).padStart(2, "0")}`; }

  async function api(url, body) {
    const response = await fetch(url, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) { const error = new Error(data.error || "default"); error.data = data; throw error; }
    return data;
  }

  function tick() {
    const now = new Date();
    $("#clockTime").textContent = now.toLocaleTimeString("fr-FR", {hour: "2-digit", minute: "2-digit", timeZone: officeTimeZone});
    $("#clockDate").textContent = now.toLocaleDateString("fr-FR", {weekday: "long", day: "numeric", month: "long", timeZone: officeTimeZone});
  }

  async function loadEmployees() {
    const grid = $("#nameGrid"), message = $("#namesMessage");
    message.textContent = ""; message.classList.remove("error");
    try {
      const {employees, timezone} = await api("/api/pointage/employees");
      officeTimeZone = timezone; tick();
      grid.replaceChildren(...employees.map((person) => {
        const button = el("button", "name-button", el("span", "avatar", person.name.trim().charAt(0).toUpperCase()), el("b", "", person.name));
        button.type = "button";
        button.addEventListener("click", () => { employee = person; pin = ""; renderDots(); $("#pinMessage").textContent = ""; $("#pinTitle").textContent = person.name; show("stepPin"); });
        return button;
      }));
      if (!employees.length) message.textContent = "Aucun salarié configuré. · لا يوجد موظفون بعد.";
    } catch (error) {
      grid.replaceChildren();
      message.classList.add("error");
      message.textContent = ERRORS[error.message] || DEFAULT_ERROR;
    }
  }

  function renderDots() {
    $("#pinDots").replaceChildren(...Array.from({length: Math.max(4, pin.length)}, (_, index) => el("i", index < pin.length ? "filled" : "")));
  }
  function buildKeypad() {
    const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"];
    $("#keypad").replaceChildren(...keys.map((key) => {
      const button = el("button", key === "OK" ? "key key-ok" : key === "⌫" ? "key key-muted" : "key", key);
      button.type = "button";
      button.setAttribute("aria-label", key === "⌫" ? "Effacer" : key === "OK" ? "Valider" : key);
      button.addEventListener("click", () => pressKey(key));
      return button;
    }));
  }
  function pressKey(key) {
    if (key === "⌫") pin = pin.slice(0, -1);
    else if (key === "OK") return submitPin();
    else if (pin.length < 8) pin += key;
    renderDots();
  }
  document.addEventListener("keydown", (event) => {
    if ($("#stepPin").hidden) return;
    if (/^\d$/.test(event.key)) pressKey(event.key);
    else if (event.key === "Backspace") pressKey("⌫");
    else if (event.key === "Enter") pressKey("OK");
  });

  async function submitPin() {
    if (pin.length < 4) { $("#pinMessage").textContent = "Le code contient au moins 4 chiffres. · الرمز من 4 أرقام على الأقل."; return; }
    try { renderActions(await api("/api/pointage/status", {employee_id: employee.id, pin})); show("stepActions"); }
    catch (error) { pin = ""; renderDots(); $("#pinMessage").textContent = ERRORS[error.message] || DEFAULT_ERROR; }
  }

  function renderActions(data) {
    $("#actionsTitle").textContent = `Bonjour ${data.name}`;
    const state = STATES[data.state];
    $("#statePill").className = `state-pill state-${data.state}`;
    $("#statePill").replaceChildren(...bilingual(state.fr, state.ar));
    $("#actionGrid").replaceChildren(...data.next.map((kind) => {
      const action = ACTIONS[kind];
      const button = el("button", `action-button tone-${action.tone}`, el("span", "action-icon", action.icon), el("b", "", action.fr), el("bdi", "", action.ar));
      button.type = "button";
      button.addEventListener("click", () => punch(kind, button));
      return button;
    }));
    $("#todayWorked").textContent = data.summary.worked ? `${formatMinutes(data.summary.worked)} travaillées` : "";
    $("#todayList").replaceChildren(...(data.punches.length ? data.punches.map((item) => el("li", "", el("time", "", item.time), el("span", "", ACTIONS[item.kind].fr)))
      : [el("li", "empty", ...bilingual("Aucun pointage", "لا يوجد تسجيل"))]));
  }

  async function punch(kind, button) {
    document.querySelectorAll(".action-button").forEach((item) => { item.disabled = true; });
    button.classList.add("busy");
    try {
      const data = await api("/api/pointage/punch", {employee_id: employee.id, pin, kind});
      const action = ACTIONS[data.recorded];
      $("#doneTitle").replaceChildren(...bilingual(`${action.fr} enregistrée`, `تم تسجيل ${action.ar}`));
      $("#doneText").textContent = `${data.name} — ${data.time}${data.summary.worked ? ` · ${formatMinutes(data.summary.worked)} aujourd’hui` : ""}`;
      pin = "";
      show("stepDone");
    } catch (error) {
      if (error.data && error.data.next) renderActions(error.data);
      else document.querySelectorAll(".action-button").forEach((item) => { item.disabled = false; });
      button.classList.remove("busy");
      alertBox(ERRORS[error.message] || DEFAULT_ERROR);
    }
  }
  function alertBox(text) {
    const box = el("p", "clock-message error", text);
    box.setAttribute("role", "alert");
    $("#actionGrid").after(box);
    setTimeout(() => box.remove(), 5000);
  }

  document.querySelectorAll("[data-back]").forEach((button) => button.addEventListener("click", reset));
  buildKeypad(); renderDots(); tick(); setInterval(tick, 15000); loadEmployees();
})();
