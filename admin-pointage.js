(() => {
  const KINDS = {in: "Arrivée", break_start: "Début pause", break_end: "Fin pause", out: "Départ"};
  const STATUS = {present: "Au bureau", break: "En pause", left: "Parti", done: "Journée complète", missing_out: "Départ non pointé", absent: "Absent", waiting: "Pas encore arrivé", off: "Repos"};
  const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  const ERRORS = {invalid_name: "Nom invalide (2 à 60 caractères).", invalid_pin: "Le PIN doit contenir 4 à 8 chiffres.", invalid_hours: "Vérifiez les horaires.", invalid_settings: "Réglages invalides (adresse réseau incorrecte ?).", invalid_punch: "Pointage invalide."};

  const $ = (selector) => document.querySelector(selector);
  let csrf = "", overview = null, networksDraft = [], openRow = null;

  function el(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    children.forEach((child) => node.append(child));
    return node;
  }
  function button(label, className, onClick) {
    const node = el("button", className, label); node.type = "button"; node.addEventListener("click", onClick); return node;
  }
  const hours = (minutes) => minutes ? `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}` : "—";
  const isoDate = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

  async function request(url, options = {}) {
    const response = await fetch(url, {...options, headers: {...(options.body ? {"Content-Type": "application/json"} : {}), ...(csrf ? {"X-CSRF-Token": csrf} : {})}});
    let data = {};
    try { data = await response.json(); } catch {}
    if (response.status === 401) { location.href = "/admin"; throw new Error("authentication_required"); }
    if (!response.ok) throw new Error(data.error || "request_failed");
    return data;
  }
  const send = (url, method, body) => request(url, {method, body: body === undefined ? undefined : JSON.stringify(body)});
  function feedback(form, text, ok) {
    const node = form.querySelector(".pt-feedback");
    node.textContent = text; node.classList.toggle("ok", !!ok);
    if (ok) setTimeout(() => { if (node.textContent === text) node.textContent = ""; }, 2500);
  }

  // ---------- day ----------
  async function loadDay(date) {
    overview = await request(`/api/admin/pointage/overview${date ? `?date=${date}` : ""}`);
    $("#dayInput").value = overview.date;
    const day = new Date(`${overview.date}T12:00:00`);
    $("#dayTitle").textContent = day.toLocaleDateString("fr-FR", {weekday: "long", day: "numeric", month: "long", year: "numeric"});
    const rows = overview.day;
    $("#statPresent").textContent = rows.filter((row) => row.status === "present").length;
    $("#statBreak").textContent = rows.filter((row) => row.status === "break").length;
    $("#statLate").textContent = rows.filter((row) => row.late).length;
    $("#statAbsent").textContent = rows.filter((row) => row.status === "absent").length;
    renderDayTable(rows);
    renderNetworkAlert();
    renderEmployees();
    if (!$("#settingsForm").dataset.loaded) fillSettings();
  }

  function renderDayTable(rows) {
    const body = $("#dayTable tbody");
    $("#dayEmpty").hidden = rows.length > 0;
    body.replaceChildren(...rows.flatMap((row) => {
      const toggle = button(openRow === row.employee_id ? "Fermer" : "Détails", "link-button", () => { openRow = openRow === row.employee_id ? null : row.employee_id; renderDayTable(overview.day); });
      const line = el("tr", "",
        el("td", "", el("b", "", row.name)),
        el("td", "", el("span", `status-chip st-${row.status}`, STATUS[row.status])),
        el("td", "", row.first_in || "—"), el("td", "", row.last_out || "—"),
        el("td", "", hours(row.breaks)), el("td", "", el("b", "", hours(row.worked))),
        el("td", row.late ? "late" : "", row.late ? `+${row.late} min` : "—"), el("td", "align-end", toggle));
      return openRow === row.employee_id ? [line, detailRow(row)] : [line];
    }));
  }

  function detailRow(row) {
    const list = el("ul", "punch-list", ...(row.punches.length ? row.punches.map((punch) => el("li", "",
      el("time", "", punch.time), el("span", "", KINDS[punch.kind]),
      punch.manual ? el("em", "manual-badge", punch.note ? `Ajouté par l’admin — ${punch.note}` : "Ajouté par l’admin") : "",
      button("Supprimer", "link-button danger", async () => { await send(`/api/admin/pointage/punches/${punch.id}`, "DELETE"); loadDay(overview.date); })))
      : [el("li", "muted", "Aucun pointage ce jour.")]));
    const form = el("form", "punch-form");
    const kind = el("select", "", ...Object.entries(KINDS).map(([value, label]) => { const option = el("option", "", label); option.value = value; return option; }));
    const time = el("input"); time.type = "time"; time.required = true;
    const note = el("input"); note.placeholder = "Motif (ex. oubli de pointage)"; note.maxLength = 200;
    const submit = el("button", "", "Ajouter le pointage"); submit.type = "submit";
    const message = el("span", "pt-feedback");
    form.append(el("b", "", "Correction manuelle"), kind, time, note, submit, message);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await send("/api/admin/pointage/punches", "POST", {employee_id: row.employee_id, date: overview.date, time: time.value, kind: kind.value, note: note.value}); loadDay(overview.date); }
      catch (error) { message.textContent = ERRORS[error.message] || "Erreur."; }
    });
    const cell = el("td", "", list, form); cell.colSpan = 8;
    return el("tr", "detail-row", cell);
  }

  function renderNetworkAlert() {
    const alert = $("#networkAlert");
    if (!overview.settings.office_networks.length) {
      alert.hidden = false; alert.className = "network-alert warn";
      alert.textContent = "Aucun réseau de bureau configuré : vos salariés peuvent pointer depuis n’importe où. Depuis le Wi-Fi du bureau, ouvrez « Horaires & réseau » et cliquez sur « Autoriser ce réseau ».";
    } else alert.hidden = true;
  }

  // ---------- month ----------
  async function loadMonth(month) {
    const data = await request(`/api/admin/pointage/month?month=${month}`);
    $("#exportLink").href = `/api/admin/pointage/export.csv?month=${month}`;
    $("#monthTable tbody").replaceChildren(...(data.employees.length ? data.employees.map((row) => el("tr", "",
      el("td", "", el("b", "", row.name)), el("td", "", String(row.present_days)), el("td", "", el("b", "", hours(row.worked))), el("td", "", hours(row.breaks)),
      el("td", row.late_count ? "late" : "", row.late_count ? `${row.late_count} (${row.late_minutes} min)` : "0"),
      el("td", row.absences ? "late" : "", String(row.absences)), el("td", row.missing_out ? "late" : "", String(row.missing_out))))
      : [el("tr", "", Object.assign(el("td", "muted", "Aucune donnée pour ce mois."), {colSpan: 7}))]));
  }

  // ---------- employees ----------
  function renderEmployees() {
    $("#employeeList").replaceChildren(...overview.employees.map((person) => {
      const name = el("input"); name.value = person.name; name.maxLength = 60; name.setAttribute("aria-label", "Nom");
      const pin = el("input"); pin.placeholder = "Nouveau PIN"; pin.inputMode = "numeric"; pin.maxLength = 8; pin.setAttribute("aria-label", "Nouveau PIN");
      const message = el("span", "pt-feedback");
      const save = button("Enregistrer", "", async () => {
        const body = {name: name.value};
        if (pin.value) body.pin = pin.value;
        try { await send(`/api/admin/pointage/employees/${person.id}`, "PATCH", body); pin.value = ""; message.textContent = "Enregistré ✓"; message.classList.add("ok"); loadDay(overview.date); }
        catch (error) { message.classList.remove("ok"); message.textContent = ERRORS[error.message] || "Erreur."; }
      });
      const toggle = button(person.active ? "Désactiver" : "Réactiver", "link-button" + (person.active ? " danger" : ""), async () => {
        await send(`/api/admin/pointage/employees/${person.id}`, "PATCH", {active: !person.active}); loadDay(overview.date);
      });
      return el("li", person.active ? "" : "inactive", name, pin, save, toggle, message);
    }));
  }
  $("#employeeForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, data = new FormData(form);
    try { await send("/api/admin/pointage/employees", "POST", {name: data.get("name"), pin: data.get("pin")}); form.reset(); feedback(form, "Salarié ajouté ✓", true); loadDay(overview.date); }
    catch (error) { feedback(form, ERRORS[error.message] || "Erreur."); }
  });

  // ---------- settings ----------
  function fillSettings() {
    const form = $("#settingsForm"), settings = overview.settings;
    form.dataset.loaded = "1";
    form.timezone.value = settings.timezone; form.work_start.value = settings.work_start; form.work_end.value = settings.work_end; form.late_tolerance.value = settings.late_tolerance;
    $("#dayChecks").replaceChildren(...WEEKDAYS.map((label, index) => {
      const box = el("input"); box.type = "checkbox"; box.name = "workday"; box.value = index; box.checked = settings.workdays.includes(index);
      return el("label", "day-check", box, label);
    }));
    networksDraft = [...settings.office_networks];
    renderNetworks();
  }
  function renderNetworks() {
    $("#networkList").replaceChildren(...(networksDraft.length ? networksDraft.map((network) => el("li", "",
      el("code", "", network), network.split("/")[0] === overview.current_ip ? el("em", "", "votre réseau actuel") : "",
      button("Retirer", "link-button danger", () => { networksDraft = networksDraft.filter((item) => item !== network); renderNetworks(); })))
      : [el("li", "muted", "Aucun réseau : pointage possible de partout.")]));
    const current = $("#addCurrentNetwork");
    const known = networksDraft.some((network) => network.split("/")[0] === overview.current_ip);
    current.textContent = known ? `Réseau actuel déjà autorisé (${overview.current_ip})` : `+ Autoriser ce réseau (${overview.current_ip})`;
    current.disabled = known;
  }
  $("#addCurrentNetwork").addEventListener("click", () => { networksDraft.push(overview.current_ip); renderNetworks(); });
  $("#settingsForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await send("/api/admin/pointage/settings", "POST", {timezone: form.timezone.value, work_start: form.work_start.value, work_end: form.work_end.value, late_tolerance: Number(form.late_tolerance.value),
        workdays: [...form.querySelectorAll("[name=workday]:checked")].map((box) => Number(box.value)), office_networks: networksDraft});
      feedback(form, "Réglages enregistrés ✓", true);
      delete form.dataset.loaded;
      loadDay(overview.date); loadMonth($("#monthInput").value);
    } catch (error) { feedback(form, ERRORS[error.message] || "Erreur."); }
  });

  // ---------- navigation ----------
  function shiftDay(delta) { const day = new Date(`${overview.date}T12:00:00`); day.setDate(day.getDate() + delta); loadDay(isoDate(day)); }
  $("#prevDay").addEventListener("click", () => shiftDay(-1));
  $("#nextDay").addEventListener("click", () => shiftDay(1));
  $("#todayBtn").addEventListener("click", () => loadDay());
  $("#dayInput").addEventListener("change", (event) => event.target.value && loadDay(event.target.value));
  $("#refreshBtn").addEventListener("click", () => loadDay(overview.date));
  $("#monthInput").addEventListener("change", (event) => event.target.value && loadMonth(event.target.value));
  $("#logoutButton").addEventListener("click", async () => { try { await send("/api/admin/logout", "POST"); } finally { location.href = "/admin"; } });

  (async () => {
    try {
      const state = await request("/api/admin/state");
      if (!state.authenticated) { location.href = "/admin"; return; }
      csrf = state.csrf || "";
      $("#dashboard").hidden = false;
      const month = isoDate(new Date()).slice(0, 7);
      $("#monthInput").value = month;
      await loadDay();
      loadMonth(month);
      setInterval(() => { if (overview && overview.date === overview.today && openRow === null) loadDay(overview.date); }, 60000);
    } catch (error) {
      if (error.message !== "authentication_required") document.body.append(el("p", "pt-empty", "Le serveur n’est pas disponible."));
    }
  })();
})();
