"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 2) => (v === null || v === undefined ? "—" : (+v).toFixed(d).replace(".", ","));
const pct = (v) => (v === null || v === undefined ? "—" : Math.round(v * 100) + "%");
const CAT = {
  star: "Звезда", preferred: "Предпочитаемый", accepted: "Принятый",
  neglected: "Пренебрегаемый", isolated: "Изолированный", rejected: "Отвергнутый",
};
const CAT_COLOR = { star: "#4f8a10", preferred: "#b1ec52", accepted: "#aeb5c0", neglected: "#eeb56b", isolated: "#dadde3", rejected: "#e2622f" };
const DARK_TEXT = new Set(["preferred", "neglected", "isolated"]);
const STATUS_KEYS = ["star", "preferred", "accepted", "neglected", "rejected", "isolated"];
const CAT_PLURAL = { star: "Звёзды", preferred: "Предпочитаемые", accepted: "Принятые",
  neglected: "Пренебрегаемые", rejected: "Отвергаемые", isolated: "Изолированные" };

function store(key, val) {
  try {
    if (val === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, val);
  } catch (e) { return null; }
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch("/api/" + url, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    toast(data.error || "Ошибка " + r.status);
    throw new Error(data.error || r.status);
  }
  return data;
}

function linesOf(text) {
  return text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

function pickFile(accept) {
  return new Promise((resolve) => {
    const inp = document.createElement("input");
    inp.type = "file";
    inp.accept = accept;
    inp.onchange = () => resolve(inp.files[0] || null);
    inp.click();
  });
}

// ------------------------------------------------------------------ router
let S = null; // текущая социометрия

window.addEventListener("hashchange", route);
route();

async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const parts = h.split("/");
  if (parts[0] === "s" && parts[1]) {
    const id = +parts[1];
    const tab = parts[2] || "input";
    try {
      S = await api("GET", "studies/" + id);
    } catch (e) {
      location.hash = "#/";
      return;
    }
    renderStudy(tab, +parts[3]);
  } else if (parts[0] === "help") {
    renderHelp();
  } else {
    renderList();
  }
  window.scrollTo(0, 0);
}

function currentCriterion() {
  const saved = +store("crit-" + S.id);
  const c = S.criteria.find((c) => c.id === saved) || S.criteria[0];
  return c ? c.id : null;
}

// ------------------------------------------------------------------ list
async function renderList() {
  const list = await api("GET", "studies");
  app.innerHTML = `
    <div class="row"><h1 class="grow">Мои социометрии</h1>
      <button id="restore">Восстановить из резервной копии</button>
      <button id="demo">Открыть демо-пример</button>
      <button class="primary" id="new">+ Новая социометрия</button></div>
    <div id="newform"></div>
    ${list.length ? `<div class="panel row no-print" style="margin-bottom:14px">
      <input type="text" id="find-study" class="grow" placeholder="Быстрый поиск по названию">
      <label><input type="checkbox" id="only-unfilled"> Только незаполненные</label>
      <label><input type="checkbox" id="only-empty"> Только без участников</label>
      <label><input type="checkbox" id="only-perc"> С перцептивными выборами</label></div>` : ""}
    ${list.length ? `<div class="cards">${list.map((s) => `
      <div class="card" data-id="${s.id}" data-name="${esc(s.name.toLocaleLowerCase())}"
           data-unfilled="${s.n_members * s.n_criteria > s.n_filled ? 1 : 0}" data-empty="${s.n_members ? 0 : 1}"
           data-perc="${s.perceptual ? 1 : 0}">
        <h3>${esc(s.name)}</h3>
        <div class="muted small">${s.n_members} участн. · ${s.n_criteria} критер. · заполнено ${s.n_filled} из ${s.n_members * s.n_criteria} · изменено ${esc(s.updated_at)}</div>
        ${s.description ? `<div class="small" style="margin-top:6px">${esc(s.description)}</div>` : ""}
        <button class="link" data-copy="${s.id}" style="margin-top:6px">Сделать копию</button>
      </div>`).join("")}</div>`
      : `<div class="panel empty">Пока нет ни одной социометрии.<br>Создайте новую или откройте демо-пример, чтобы посмотреть, как всё работает.</div>`}
  `;
  $$(".card").forEach((c) => (c.onclick = () => (location.hash = `#/s/${c.dataset.id}/input`)));
  $$("[data-copy]").forEach((b) => (b.onclick = async (event) => {
    event.stopPropagation();
    const result = await api("POST", `studies/${b.dataset.copy}/copy`);
    location.hash = `#/s/${result.id}/setup`;
  }));
  if (list.length) {
    const applyFilters = () => {
      const q = $("#find-study").value.trim().toLocaleLowerCase();
      $$(".card").forEach((card) => {
        card.hidden = !card.dataset.name.includes(q) ||
          ($("#only-unfilled").checked && card.dataset.unfilled !== "1") ||
          ($("#only-empty").checked && card.dataset.empty !== "1") ||
          ($("#only-perc").checked && card.dataset.perc !== "1");
      });
    };
    $("#find-study").oninput = applyFilters;
    for (const id of ["only-unfilled", "only-empty", "only-perc"]) $("#" + id).onchange = applyFilters;
  }
  $("#demo").onclick = async () => {
    const r = await api("POST", "demo");
    location.hash = `#/s/${r.id}/results`;
  };
  $("#restore").onclick = async () => {
    const f = await pickFile(".json");
    if (!f) return;
    let data;
    try { data = JSON.parse(await f.text()); } catch (e) { return toast("Файл не читается как JSON"); }
    const r = await api("POST", "restore", data);
    location.hash = `#/s/${r.id}/input`;
  };
  $("#new").onclick = showNewForm;
  if (!list.length) showNewForm();
}

function showNewForm() {
  $("#newform").innerHTML = `
    <div class="panel">
      <h2 style="margin-top:0">Новая социометрия</h2>
      <div class="row"><div class="grow"><label>Название группы / исследования</label><br>
        <input type="text" id="n-name" style="width:100%" placeholder="Например: 7 «А» класс, отдел продаж"></div></div>
      <div class="two" style="margin-top:12px">
        <div><label>Участники — по одному на строку (можно вставить столбец из Excel)</label>
          <textarea id="n-members" placeholder="Иванов Иван&#10;Петрова Мария&#10;..."></textarea></div>
        <div><label>Критерии (вопросы) — по одному на строку</label>
          <textarea id="n-criteria">С кем бы вы хотели работать вместе?</textarea></div>
      </div>
      <div class="row" style="margin-top:10px">
        <label>Лимит «+» выборов <input type="number" id="n-maxpos" min="0" value="3"></label>
        <label>Лимит «−» выборов <input type="number" id="n-maxneg" min="0" value="3"></label>
        <label><input type="checkbox" id="n-perc"> Перцептивные выборы («кто, по-вашему, выбрал вас»)</label>
        <label><input type="checkbox" id="n-optimistic"> Оптимистичный расчёт статусов</label>
        <span class="muted small">0 = без ограничения</span>
      </div>
      <div style="margin-top:14px"><label for="n-file">Файл участников или заполненных выборов (.xls, .xlsx, .csv)</label><br>
        <input type="file" id="n-file" accept=".xls,.xlsx,.csv,.txt"></div>
      <div class="row" style="margin-top:8px"><label><input type="checkbox" id="n-filled"> Файл уже содержит выборы</label>
        <a href="/templates/participants.xlsx" download>Пример списка</a>
        <a href="/templates/choices.xlsx" download>Пример файла с выборами</a></div>
      <div class="row" style="margin-top:14px"><button class="primary" id="n-create">Создать</button>
        <span class="muted small">Участников можно добавить и позже</span></div>
    </div>`;
  $("#n-name").focus();
  $("#n-create").onclick = async () => {
    const study = {
      name: $("#n-name").value,
      members: linesOf($("#n-members").value),
      criteria: linesOf($("#n-criteria").value),
      max_pos: +$("#n-maxpos").value, max_neg: +$("#n-maxneg").value,
      perceptual: $("#n-perc").checked,
      optimistic: $("#n-optimistic").checked,
    };
    const file = $("#n-file").files[0];
    let r;
    if (file) {
      const fd = new FormData();
      fd.append("study", JSON.stringify(study));
      fd.append("file", file);
      fd.append("mode", $("#n-filled").checked ? "matrix" : "members");
      r = await api("POST", "studies/import", fd);
    } else {
      r = await api("POST", "studies", study);
    }
    location.hash = `#/s/${r.id}/${file || study.members.length ? "input" : "setup"}`;
  };
}

// ------------------------------------------------------------------ study shell
function renderStudy(tab, personId) {
  const t = (k, label) => `<a href="#/s/${S.id}/${k}" class="${tab === k || (k === "results" && tab === "person") ? "active" : ""}">${label}</a>`;
  app.innerHTML = `
    <div class="muted small"><a href="#/">← все социометрии</a></div>
    <h1>${esc(S.name)}</h1>
    <div class="tabs">${t("setup", "Участники и критерии")}${t("input", "Ввод выборов")}${t("results", "Результаты")}</div>
    <div id="tab"></div>`;
  const el = $("#tab");
  if (tab === "setup") renderSetup(el);
  else if (tab === "results") renderResults(el);
  else if (tab === "person") renderPerson(el, personId);
  else renderInput(el);
}

async function reloadStudy() {
  S = await api("GET", "studies/" + S.id);
}

// ------------------------------------------------------------------ setup tab
function renderSetup(el) {
  el.innerHTML = `
    <div class="two">
      <div>
        <div class="panel">
          <h2 style="margin-top:0">Участники <span class="muted">(${S.members.length})</span></h2>
          <ol class="list">${S.members.map((m, i) => `
            <li><span class="num">${i + 1}</span><input type="text" value="${esc(m.name)}" data-mid="${m.id}">
            ${m.has_photo ? `<img class="avatar" src="/api/members/${m.id}/photo" alt="">
              <button class="link" data-remove-photo="${m.id}" title="Удалить фото">убрать фото</button>` : ""}
            <button class="link" data-photo="${m.id}" title="Загрузить фото">${m.has_photo ? "сменить фото" : "добавить фото"}</button>
            <button class="link" data-del-m="${m.id}" title="Удалить">✕</button></li>`).join("")}</ol>
          <h3>Добавить участников</h3>
          <textarea id="add-m" placeholder="По одному на строку"></textarea>
          <div class="row" style="margin-top:8px">
            <button class="primary" id="add-m-btn">Добавить</button>
            <button id="import-btn">Загрузить из файла (.xls, .xlsx, .csv)</button>
          </div>
          <div class="row" style="margin-top:8px"><label><input type="checkbox" id="import-filled"> Файл уже содержит выборы</label>
            <a href="/templates/participants.xlsx" download>Пример списка</a>
            <a href="/templates/choices.xlsx" download>Пример выборов</a></div>
          <p class="muted small">Файл со списком: один столбец с ФИО. Файл с выборами: столбцы «№», «ФИО», затем номера участников;
            в ячейках <code>+</code> / <code>1</code> для положительного выбора и <code>-</code> / <code>-1</code> для отрицательного.
            Матрица будет загружена в новый критерий.</p>
        </div>
      </div>
      <div>
        <div class="panel">
          <h2 style="margin-top:0">Критерии (вопросы)</h2>
          <ol class="list">${S.criteria.map((c, i) => `
            <li><span class="num">${i + 1}</span><input type="text" value="${esc(c.name)}" data-cid="${c.id}">
            <button class="link" data-del-c="${c.id}" title="Удалить">✕</button></li>`).join("")}</ol>
          <div class="row" style="margin-top:8px"><input type="text" id="add-c" class="grow" placeholder="Например: Кого бы вы позвали в поход?">
            <button id="add-c-btn">Добавить</button></div>
        </div>
        <div class="panel">
          <h2 style="margin-top:0">Настройки</h2>
          <label>Название</label><br><input type="text" id="s-name" style="width:100%" value="${esc(S.name)}">
          <div style="margin-top:8px"><label>Описание / заметки</label><br>
            <textarea id="s-desc" style="min-height:60px">${esc(S.description)}</textarea></div>
          <div class="row" style="margin-top:8px">
            <label>Лимит «+» <input type="number" id="s-maxpos" min="0" value="${S.max_pos}"></label>
            <label>Лимит «−» <input type="number" id="s-maxneg" min="0" value="${S.max_neg}"></label>
            <label><input type="checkbox" id="s-perc" ${S.perceptual ? "checked" : ""}> Перцептивные выборы</label>
            <label><input type="checkbox" id="s-optimistic" ${S.optimistic ? "checked" : ""}> Оптимистичный расчёт статусов</label>
          </div>
          <div class="row" style="margin-top:12px"><button class="primary" id="s-save">Сохранить</button></div>
        </div>
        <div class="panel">
          <h2 style="margin-top:0">Данные</h2>
          <div class="row">
            <a class="btn" href="/api/studies/${S.id}/backup">Скачать резервную копию (.json)</a>
            <button class="danger" id="s-del">Удалить социометрию</button>
          </div>
        </div>
      </div>
    </div>`;

  $$("[data-mid]", el).forEach((inp) => (inp.onchange = async () => {
    await api("PUT", "members/" + inp.dataset.mid, { name: inp.value });
    toast("Сохранено");
  }));
  $$("[data-photo]", el).forEach((button) => (button.onclick = async () => {
    const file = await pickFile("image/png,image/jpeg,image/webp");
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    await api("POST", `members/${button.dataset.photo}/photo`, fd);
    await reloadStudy(); renderSetup(el);
  }));
  $$("[data-remove-photo]", el).forEach((button) => (button.onclick = async () => {
    await api("DELETE", `members/${button.dataset.removePhoto}/photo`);
    await reloadStudy(); renderSetup(el);
  }));
  $$("[data-cid]", el).forEach((inp) => (inp.onchange = async () => {
    await api("PUT", "criteria/" + inp.dataset.cid, { name: inp.value });
    toast("Сохранено");
  }));
  $$("[data-del-m]", el).forEach((b) => (b.onclick = async () => {
    const m = S.members.find((x) => x.id === +b.dataset.delM);
    if (!confirm(`Удалить участника «${m.name}» вместе со всеми его выборами?`)) return;
    await api("DELETE", "members/" + m.id);
    await reloadStudy(); renderStudy("setup");
  }));
  $$("[data-del-c]", el).forEach((b) => (b.onclick = async () => {
    const c = S.criteria.find((x) => x.id === +b.dataset.delC);
    if (!confirm(`Удалить критерий «${c.name}» и все выборы по нему?`)) return;
    await api("DELETE", "criteria/" + c.id);
    await reloadStudy(); renderStudy("setup");
  }));
  $("#add-m-btn").onclick = async () => {
    const names = linesOf($("#add-m").value);
    if (!names.length) return;
    await api("POST", `studies/${S.id}/members`, { names });
    await reloadStudy(); renderStudy("setup");
  };
  $("#import-btn").onclick = () => importFile(null, "setup", $("#import-filled").checked ? "matrix" : "members");
  const addC = async () => {
    if (!$("#add-c").value.trim()) return;
    await api("POST", `studies/${S.id}/criteria`, { name: $("#add-c").value });
    await reloadStudy(); renderStudy("setup");
  };
  $("#add-c-btn").onclick = addC;
  $("#add-c").onkeydown = (e) => e.key === "Enter" && addC();
  $("#s-save").onclick = async () => {
    S = await api("PUT", "studies/" + S.id, {
      name: $("#s-name").value, description: $("#s-desc").value,
      max_pos: +$("#s-maxpos").value, max_neg: +$("#s-maxneg").value, perceptual: $("#s-perc").checked,
      optimistic: $("#s-optimistic").checked,
    });
    toast("Настройки сохранены");
    renderStudy("setup");
  };
  $("#s-del").onclick = async () => {
    if (!confirm(`Удалить «${S.name}» безвозвратно?`)) return;
    await api("DELETE", "studies/" + S.id);
    location.hash = "#/";
  };
}

async function importFile(criterionId, backTab, mode = "auto") {
  const f = await pickFile(".xls,.xlsx,.csv,.txt");
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  fd.append("mode", mode);
  if (criterionId) fd.append("criterion_id", criterionId);
  const r = await api("POST", `studies/${S.id}/import`, fd);
  if (r.mode === "members") toast(`Добавлено участников: ${r.added}`);
  else {
    toast(`Загружено выборов: ${r.choices}, новых участников: ${r.added}`);
    store("crit-" + S.id, r.criterion_id);
  }
  await reloadStudy();
  renderStudy(r.mode === "matrix" ? "input" : backTab);
}

// ------------------------------------------------------------------ input tab
let inputMode = "main"; // main | perc

function critTabs(cid) {
  if (S.criteria.length < 2) return "";
  return `<div class="row" style="margin-bottom:10px">${S.criteria.map((c) =>
    `<button data-crit="${c.id}" class="${c.id === cid ? "on" : ""}">${esc(c.name)}</button>`).join("")}</div>`;
}

function bindCritTabs(el, rerender) {
  $$("[data-crit]", el).forEach((b) => (b.onclick = () => { store("crit-" + S.id, b.dataset.crit); rerender(); }));
}

function renderInput(el) {
  if (!S.members.length || !S.criteria.length) {
    el.innerHTML = `<div class="panel empty">Сначала добавьте ${!S.members.length ? "участников" : "хотя бы один критерий"}
      на вкладке <a href="#/s/${S.id}/setup">«Участники и критерии»</a>.</div>`;
    return;
  }
  if (!S.perceptual) inputMode = "main";
  const cid = currentCriterion();
  const crit = S.criteria.find((c) => c.id === cid);
  const M = S.members;
  const ch = new Map(); // "a-b" -> {main, perc}
  for (const c of S.choices) {
    if (c.criterion_id !== cid) continue;
    const k = c.from_id + "-" + c.to_id;
    const o = ch.get(k) || {};
    if (c.kind === "pos" || c.kind === "neg") o.main = c.kind; else o.perc = c.kind;
    ch.set(k, o);
  }
  const cellHtml = (a, b) => {
    if (a === b) return `<td class="self"></td>`;
    const o = ch.get(a + "-" + b) || {};
    const cls = o.main === "pos" ? "pos" : o.main === "neg" ? "neg" : "";
    const mark = o.main === "pos" ? "+" : o.main === "neg" ? "−" : "";
    const p = o.perc ? `<span class="p">${o.perc === "ppos" ? "п+" : "п−"}</span>` : "";
    return `<td class="cell ${cls}" data-a="${a}" data-b="${b}">${mark}${p}</td>`;
  };
  const cnt = (a, kind, dir) => S.choices.filter((c) => c.criterion_id === cid && c.kind === kind &&
    (dir === "out" ? c.from_id === a : c.to_id === a)).length;
  const overP = (n) => (S.max_pos && n > S.max_pos ? "over" : "");
  const overN = (n) => (S.max_neg && n > S.max_neg ? "over" : "");

  el.innerHTML = `
    ${critTabs(cid)}
    <div class="panel">
      <div class="row">
        <div class="grow"><b>${esc(crit.name)}</b><div class="muted small">
          Строка — кто выбирает, столбец — кого выбирают. Щелчок по ячейке: пусто → <b style="color:var(--accent)">+</b> → <b style="color:var(--neg)">−</b> → пусто.
          ${S.max_pos || S.max_neg ? `Лимит: ${S.max_pos || "∞"} «+» и ${S.max_neg || "∞"} «−» на человека.` : ""}</div></div>
        ${S.perceptual ? `<div class="mode"><button data-mode="main" class="${inputMode === "main" ? "on" : ""}">Выборы</button>
          <button data-mode="perc" class="perc ${inputMode === "perc" ? "on" : ""}">Перцептивные (ожидания)</button></div>` : ""}
      </div>
      ${inputMode === "perc" ? `<div class="small" style="margin-top:8px;color:var(--perc)">Режим ожиданий: в строке участника отметьте тех, кто, по его мнению, выбрал <b>его</b> (п+) или отверг (п−).</div>` : ""}
    </div>
    <div class="matrix-wrap"><table class="matrix">
      <thead><tr><th class="corner rowh muted small">выбирает ↓ / кого →</th>
        ${M.map((m, i) => `<th title="${esc(m.name)}"><span class="vert">${i + 1}. ${esc(m.name)}</span></th>`).join("")}
        <th class="tot" title="Отдано положительных">+</th><th class="tot" title="Отдано отрицательных">−</th>
        <th class="tot" title="Анкета заполнена">готово</th>
        ${S.perceptual ? `<th class="tot" title="Ожиданий">п</th>` : ""}</tr></thead>
      <tbody>${M.map((m, i) => {
        const po = cnt(m.id, "pos", "out"), no = cnt(m.id, "neg", "out");
        return `<tr data-row="${m.id}"><th class="rowh">${i + 1}. ${esc(m.name)}</th>
          ${M.map((x) => cellHtml(m.id, x.id)).join("")}
          <td class="tot ${overP(po)}">${po}</td><td class="tot ${overN(no)}">${no}</td>
          <td class="tot"><input type="checkbox" data-filled="${m.id}" aria-label="Анкета ${esc(m.name)} заполнена"
            ${S.filled.some((q) => q.criterion_id === cid && q.member_id === m.id) ? "checked" : ""}></td>
          ${S.perceptual ? `<td class="tot">${cnt(m.id, "ppos", "out") + cnt(m.id, "pneg", "out")}</td>` : ""}</tr>`;
      }).join("")}
      <tr class="totrow"><th class="rowh">Получено +</th>${M.map((m) => `<td class="tot" style="color:var(--accent)">${cnt(m.id, "pos", "in")}</td>`).join("")}<td colspan="3"></td></tr>
      <tr class="totrow"><th class="rowh">Получено −</th>${M.map((m) => `<td class="tot" style="color:var(--neg)">${cnt(m.id, "neg", "in")}</td>`).join("")}<td colspan="3"></td></tr>
      </tbody></table></div>
    <div class="row" style="margin-top:12px">
      <div class="legend grow"><span><span class="sw" style="background:var(--accent-soft)"></span>положительный выбор</span>
        <span><span class="sw" style="background:var(--neg-soft)"></span>отрицательный выбор</span>
        ${S.perceptual ? `<span><b style="color:var(--perc)">п+ / п−</b> ожидание</span>` : ""}
        <span>правый щелчок — очистить ячейку</span></div>
      <button id="imp">Загрузить выборы из файла</button>
      <button class="danger" id="clr">Очистить все выборы по критерию</button>
      <a class="btn primary" href="#/s/${S.id}/results">Результаты →</a>
    </div>`;

  bindCritTabs(el, () => renderInput(el));
  $$("[data-filled]", el).forEach((checkbox) => (checkbox.onchange = async () => {
    const memberId = +checkbox.dataset.filled;
    try {
      await api("POST", "questionnaire", { criterion_id: cid, member_id: memberId, filled: checkbox.checked });
      S.filled = S.filled.filter((q) => !(q.criterion_id === cid && q.member_id === memberId));
      if (checkbox.checked) S.filled.push({ criterion_id: cid, member_id: memberId });
      toast("Сохранено локально");
    } catch (e) { checkbox.checked = !checkbox.checked; }
  }));
  $$("[data-mode]", el).forEach((b) => (b.onclick = () => { inputMode = b.dataset.mode; renderInput(el); }));
  $("#imp").onclick = () => importFile(cid, "input");
  $("#clr").onclick = async () => {
    if (!confirm("Удалить все выборы по этому критерию?")) return;
    await api("POST", `criteria/${cid}/clear`);
    await reloadStudy(); renderInput(el);
  };

  const table = $("table.matrix", el);
  const apply = async (td, next) => {
    const a = +td.dataset.a, b = +td.dataset.b;
    const perceptual = inputMode === "perc";
    const group = perceptual ? ["ppos", "pneg"] : ["pos", "neg"];
    S.choices = S.choices.filter((c) => !(c.criterion_id === cid && c.from_id === a && c.to_id === b && group.includes(c.kind)));
    if (next) S.choices.push({ criterion_id: cid, from_id: a, to_id: b, kind: next });
    const sx = window.scrollX, sy = window.scrollY, wrap = $(".matrix-wrap", el), wl = wrap.scrollLeft, wt = wrap.scrollTop;
    renderInput(el);
    const w2 = $(".matrix-wrap", el); w2.scrollLeft = wl; w2.scrollTop = wt; window.scrollTo(sx, sy);
    try {
      await api("POST", "choice", { criterion_id: cid, from_id: a, to_id: b, kind: next, perceptual });
    } catch (e) {
      await reloadStudy(); renderInput(el);
    }
  };
  table.addEventListener("click", (e) => {
    const td = e.target.closest("td.cell");
    if (!td) return;
    const o = ch.get(td.dataset.a + "-" + td.dataset.b) || {};
    if (inputMode === "perc") apply(td, { undefined: "ppos", ppos: "pneg", pneg: null }[o.perc]);
    else apply(td, { undefined: "pos", pos: "neg", neg: null }[o.main]);
  });
  table.addEventListener("contextmenu", (e) => {
    const td = e.target.closest("td.cell");
    if (!td) return;
    e.preventDefault();
    apply(td, null);
  });
  table.addEventListener("mouseover", (e) => {
    const tr = e.target.closest("tr[data-row]");
    $$("tr.hl", table).forEach((x) => x !== tr && x.classList.remove("hl"));
    if (tr) tr.classList.add("hl");
  });
}

// ------------------------------------------------------------------ results tab
async function renderResults(el) {
  const cid = currentCriterion();
  if (!cid) {
    el.innerHTML = `<div class="panel empty">Нет данных для расчёта. Добавьте участников и критерии на вкладке
      <a href="#/s/${S.id}/setup">«Участники и критерии»</a>.</div>`;
    return;
  }
  const R = await api("GET", `criteria/${cid}/results`);
  const G = R.group;
  const byId = Object.fromEntries(R.members.map((m) => [m.id, m]));
  const st = (v, l, h) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div>${h ? `<div class="h">${h}</div>` : ""}</div>`;
  const lvl = (v, lo, hi) => (v === null ? "" : v >= hi ? "высокий уровень" : v >= lo ? "средний уровень" : "низкий уровень");

  el.innerHTML = `
    ${critTabs(cid)}
    <div class="row" style="margin-bottom:10px"><div class="grow"><b>${esc(R.criterion.name)}</b></div>
      <a class="btn" href="/api/criteria/${cid}/results.csv">Скачать CSV (Excel)</a>
      <button onclick="window.print()">Печать / PDF</button></div>

    <h2>Групповые индексы</h2>
    <div class="stats">
      ${st(G.n, "участников", `выборов: ${G.total_pos} «+» и ${G.total_neg} «−»`)}
      ${st(fmt(G.cohesion), "Сплочённость (взаимность +)", `${G.mutual_pos_pairs} взаимных пар из ${G.n * (G.n - 1) / 2} возможных`)}
      ${st(fmt(G.conflict), "Конфликтность", `${G.mutual_neg_pairs} пар взаимного отвержения`)}
      ${st(pct(G.reciprocity), "Доля взаимных «+» выборов", lvl(G.reciprocity, 0.3, 0.6))}
      ${st(fmt(G.expansiveness_total), "Эмоц. экспансивность группы", "среднее число всех выборов на человека")}
      ${st(fmt(G.reference), "Референтность группы", "взаимных положительных пар / всех положительных выборов")}
      ${st(pct(G.tension), "Напряжённость", "доля «−» среди всех выборов")}
      ${st(pct(G.wellbeing), "КБВ (благополучие отношений)", "доля звёзд и предпочитаемых · " + lvl(G.wellbeing, 0.35, 0.6))}
      ${st(pct(G.isolation), "Индекс изолированности", "доля изолированных и отвергнутых")}
      ${R.study.perceptual ? st(pct(G.perceptual_accuracy_pos), "Точность ожиданий «+»", "сколько ожиданий оправдалось") : ""}
    </div>

    <h2>Статусная структура</h2>
    <div class="panel">
      <div style="display:flex;height:26px;border-radius:6px;overflow:hidden">${Object.entries(G.categories).filter(([, n]) => n)
        .map(([k, n]) => `<div title="${CAT[k]}: ${n}" style="flex:${n};background:${CAT_COLOR[k]};color:${DARK_TEXT.has(k) ? "#15181e" : "#fff"};font-size:12px;display:flex;align-items:center;justify-content:center">${n}</div>`).join("")}</div>
      <div class="legend" style="margin-top:8px">${Object.entries(G.categories).map(([k, n]) =>
        `<span><span class="sw" style="background:${CAT_COLOR[k]}"></span>${CAT[k]}: <b>${n}</b></span>`).join("")}</div>
      <div class="muted small" style="margin-top:6px">Среднее число полученных «+»: ${fmt(G.mean_received)}, σ = ${fmt(G.sd_received)}.
        Звёзды — от двух средних «+»; предпочитаемые — от полутора средних «+» при малом числе «−»;
        пренебрегаемые — мало «+» или много «−»; отвергаемые — мало «+» при наличии «−»; изолированные — без полученных выборов.
        ${S.optimistic ? "Включён оптимистичный расчёт статусов." : ""}</div>
    </div>

    <h2>Статусы в группе</h2>
    <div class="panel status-chart-panel" id="status-chart-panel">
      <div class="row status-chart-head no-print">
        <div class="grow muted small">Распределение участников по статусным группам</div>
        <label class="chart-choice"><input type="checkbox" id="chart-plotly" aria-controls="status-chart-plotly"> Plotly</label>
        <label class="chart-choice"><input type="checkbox" id="chart-matplotlib" aria-controls="status-chart-matplotlib"> Matplotlib</label>
      </div>
      <div id="status-chart-plotly" class="status-chart-canvas"></div>
      <div id="status-chart-matplotlib" class="status-chart-canvas" hidden>
        <img id="status-chart-image" alt="Плоская диаграмма статусов в группе">
        <div class="muted small" id="status-chart-image-error" hidden>Не удалось построить график Matplotlib. Установите зависимости из requirements.txt.</div>
      </div>
      <div class="row status-chart-download no-print">
        <button id="chart-download-svg">Скачать SVG</button>
        <button id="chart-download-plotly-png">Скачать PNG · 2400 × 1800 · 300 DPI</button>
        <a class="btn" id="chart-download-mpl" href="/api/criteria/${cid}/status-chart.png?download=1" hidden>Скачать PNG · 300 DPI</a>
      </div>
      <div class="status-chart-groups" id="status-chart-groups"></div>
      <div class="status-chart-members muted small" id="status-chart-members" aria-live="polite">Нажмите на сектор или категорию, чтобы увидеть участников.</div>
    </div>

    <h2>Взаимные и парадоксальные выборы</h2>
    <div class="panel pair-list">
      ${pairSection("Взаимно-положительные", R.pairs.mutual_pos, byId)}
      ${pairSection("Взаимно-отрицательные", R.pairs.mutual_neg, byId)}
      ${pairSection("Парадоксальные (+/−)", R.pairs.paradoxical, byId)}
    </div>

    <h2>Социограмма</h2>
    <div class="graph-box" id="g1"></div>
    <div class="legend" style="margin-top:6px">
      <span><svg width="34" height="10"><line x1="2" y1="5" x2="32" y2="5" stroke="#4f8a10" stroke-width="1.6"/></svg>выбор «+»</span>
      <span><svg width="34" height="10"><line x1="2" y1="5" x2="32" y2="5" stroke="#4f8a10" stroke-width="4"/></svg>взаимный «+»</span>
      <span><svg width="34" height="10"><line x1="2" y1="5" x2="32" y2="5" stroke="#e2622f" stroke-width="1.6" stroke-dasharray="5 3"/></svg>выбор «−»</span>
      ${Object.keys(CAT).map((k) => `<span><span class="sw" style="background:${CAT_COLOR[k]};border-radius:50%"></span>${CAT[k]}</span>`).join("")}
      <span>Размер кружка — число полученных «+». Узлы можно перетаскивать, колесо мыши — масштаб.</span>
    </div>

    <h2>Социограмма-мишень</h2>
    <div class="graph-box" id="g2"></div>
    <div class="muted small" style="margin-top:6px">В центре — звёзды, далее предпочитаемые, принятые; на внешнем круге — изолированные и отвергнутые.</div>

    <h2>Социограмма взаимных выборов</h2>
    <div class="graph-box" id="g3"></div>

    <h2>Индивидуальные показатели</h2>
    <div class="panel" style="padding:0;overflow:auto"><table class="data" id="ind"></table></div>
    <div class="muted small">Статус + = получено «+» / (N−1); статус − = получено «−» / (N−1); сводный статус = (получено «+» − получено «−») / (N−1);
      экспансивность = отдано выборов / (N−1); Куд в отчёте = получено «+» / отдано «+».
      ${R.study.perceptual ? "Точность ожиданий = оправдавшиеся ожидания / все ожидания; осознанность = угаданные выборы / полученные выборы." : ""}</div>

    <h2>Социоматрица</h2>
    <div class="matrix-wrap"><table class="matrix">
      <thead><tr><th class="corner rowh"></th>${R.members.map((m, i) => `<th title="${esc(m.name)}"><span class="vert">${i + 1}. ${esc(m.name)}</span></th>`).join("")}
      <th class="tot">+</th><th class="tot">−</th><th class="tot">взаимн.</th></tr></thead>
      <tbody>${R.members.map((m, i) => `<tr><th class="rowh">${i + 1}. ${esc(m.name)}</th>${R.members.map((x) => {
        if (x.id === m.id) return `<td class="self"></td>`;
        const e = R.edges.find((e) => e.source === m.id && e.target === x.id);
        const back = e && R.edges.find((b) => b.source === x.id && b.target === m.id && b.kind === e.kind);
        return e ? `<td class="${e.kind}" style="${back ? "box-shadow:inset 0 0 0 2px currentColor" : ""}">${e.kind === "pos" ? "+" : "−"}</td>` : `<td></td>`;
      }).join("")}<td class="tot">${m.pos_out}</td><td class="tot">${m.neg_out}</td><td class="tot">${m.mutual_pos}</td></tr>`).join("")}
      <tr class="totrow"><th class="rowh">Получено +</th>${R.members.map((m) => `<td class="tot">${m.pos_in}</td>`).join("")}<td colspan="3"></td></tr>
      <tr class="totrow"><th class="rowh">Получено −</th>${R.members.map((m) => `<td class="tot">${m.neg_in}</td>`).join("")}<td colspan="3"></td></tr>
      <tr class="totrow"><th class="rowh">Место</th>${R.members.map((m) => `<td class="tot">${m.rank}</td>`).join("")}<td colspan="3"></td></tr>
      </tbody></table></div>
    <div class="muted small" style="margin-top:4px">Обведённые ячейки — взаимные выборы.</div>
  `;
  bindCritTabs(el, () => renderResults(el));
  bindStatusChart(R, cid);
  renderIndividual(R);
  const g1 = new Graph($("#g1"), R, "force");
  new Graph($("#g2"), R, "target", g1);
  new Graph($("#g3"), R, "force", null, { mutualOnly: true });
}

let plotlyLoader;
function loadPlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (!plotlyLoader) plotlyLoader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vendor/plotly.min.js";
    script.onload = () => window.Plotly ? resolve(window.Plotly) : reject(new Error("Plotly не загрузился"));
    script.onerror = () => reject(new Error("Plotly не загрузился"));
    document.head.appendChild(script);
  }).catch((error) => { plotlyLoader = null; throw error; });
  return plotlyLoader;
}

function bindStatusChart(R, cid) {
  const panel = $("#status-chart-panel");
  const counts = R.group.categories;
  const total = R.group.n;
  const members = Object.fromEntries(STATUS_KEYS.map((key) => [key, R.members.filter((m) => m.category === key)]));
  const groups = $("#status-chart-groups", panel);
  const details = $("#status-chart-members", panel);
  const plotlyBox = $("#status-chart-plotly", panel);
  const mplBox = $("#status-chart-matplotlib", panel);
  const mplImage = $("#status-chart-image", panel);
  const plotlyCheck = $("#chart-plotly", panel);
  const mplCheck = $("#chart-matplotlib", panel);
  const svgButton = $("#chart-download-svg", panel);
  const pngButton = $("#chart-download-plotly-png", panel);
  const mplDownload = $("#chart-download-mpl", panel);
  let active = "";
  let plotlyDrawn = false;

  groups.innerHTML = STATUS_KEYS.map((key) => {
    const count = counts[key] || 0;
    const share = total ? Math.round(count / total * 100) : 0;
    return `<button class="status-chart-group" data-category="${key}" type="button" aria-pressed="false">
      <span class="sw" style="background:${CAT_COLOR[key]}"></span><span>${CAT_PLURAL[key]}</span>
      <b>${count} · ${share}%</b></button>`;
  }).join("");

  function selectCategory(key) {
    $$(".status-chart-group", groups).forEach((button) =>
      button.setAttribute("aria-pressed", button.dataset.category === key ? "true" : "false"));
    const names = members[key];
    details.innerHTML = `<b>${CAT_PLURAL[key]} (${names.length})</b><div>${names.length
      ? names.map((m) => `<a href="#/s/${S.id}/person/${m.id}">${esc(m.name)}</a>`).join(" · ")
      : "Участников нет."}</div>`;
  }
  $$(".status-chart-group", groups).forEach((button) =>
    button.onclick = () => selectCategory(button.dataset.category));

  async function drawPlotly() {
    if (plotlyDrawn) return;
    try {
      const Plotly = await loadPlotly();
      if (!plotlyBox.isConnected) return;
      const keys = STATUS_KEYS.filter((key) => counts[key] > 0);
      if (!keys.length) {
        plotlyBox.innerHTML = `<div class="empty">Пока нет участников для диаграммы.</div>`;
        return;
      }
      await Plotly.newPlot(plotlyBox, [{
        type: "pie", hole: 0.58, direction: "clockwise",
        labels: keys.map((key) => CAT_PLURAL[key]), values: keys.map((key) => counts[key]),
        customdata: keys, marker: { colors: keys.map((key) => CAT_COLOR[key]), line: { color: "#fff", width: 2 } },
        text: keys.map((key) => `${Math.round(counts[key] / total * 100)}%`),
        textinfo: "text", textposition: "inside", insidetextfont: { size: 15, color: "#15181e" },
        hovertemplate: "%{label}: %{value} чел. (%{percent})<extra></extra>", sort: false,
      }], {
        paper_bgcolor: "#fff", plot_bgcolor: "#fff", showlegend: false,
        margin: { l: 16, r: 16, t: 8, b: 8 }, height: 400,
        font: { family: "Golos Text, Arial, sans-serif", color: "#15181e" },
        annotations: [{ text: `<b>${total}</b><br>участников`, x: 0.5, y: 0.5,
          xref: "paper", yref: "paper", showarrow: false, font: { size: 18 } }],
      }, { responsive: true, displayModeBar: false });
      plotlyBox.on("plotly_click", (event) => selectCategory(event.points[0].customdata));
      plotlyDrawn = true;
    } catch (error) {
      plotlyBox.innerHTML = `<div class="empty">Не удалось загрузить локальный Plotly.</div>`;
      toast(error.message);
    }
  }

  function activate(renderer) {
    active = renderer;
    store("status-chart-renderer", renderer);
    plotlyCheck.checked = renderer === "plotly";
    mplCheck.checked = renderer === "matplotlib";
    plotlyBox.hidden = renderer !== "plotly";
    mplBox.hidden = renderer !== "matplotlib";
    svgButton.hidden = pngButton.hidden = renderer !== "plotly";
    mplDownload.hidden = renderer !== "matplotlib";
    if (renderer === "plotly") drawPlotly();
    else if (!mplImage.src) mplImage.src = `/api/criteria/${cid}/status-chart.png`;
  }
  plotlyCheck.onchange = () => activate("plotly");
  mplCheck.onchange = () => activate("matplotlib");
  mplImage.onerror = () => { $("#status-chart-image-error", panel).hidden = false; };
  async function downloadPlotly(format) {
    await drawPlotly();
    if (!plotlyDrawn) return;
    const opts = { format, filename: `статусы-${S.id}` };
    if (format === "png") { opts.width = 2400; opts.height = 1800; }
    else { opts.width = 1200; opts.height = 900; }
    try {
      if (format === "svg") return await window.Plotly.downloadImage(plotlyBox, opts);
      const dataUrl = await window.Plotly.toImage(plotlyBox, opts);
      const bytes = new Uint8Array(await (await fetch(dataUrl)).arrayBuffer());
      const output = setPngDpi(bytes, 300);
      const url = URL.createObjectURL(new Blob([output], { type: "image/png" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `${opts.filename}-300dpi.png`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    catch (error) { toast("Не удалось сохранить диаграмму: " + error.message); }
  }
  svgButton.onclick = () => downloadPlotly("svg");
  pngButton.onclick = () => downloadPlotly("png");
  activate(store("status-chart-renderer") === "matplotlib" ? "matplotlib" : "plotly");
}

function pairSection(title, pairs, byId) {
  return `<h3>${title} (${pairs.length})</h3><p>${pairs.length ? pairs.map(([a, b]) =>
    `${esc(byId[a].name)} — ${esc(byId[b].name)}`).join(", ") : "Таких выборов нет."}</p>`;
}

function renderIndividual(R) {
  const cols = [
    ["rank", "Место"], ["name", "Участник"], ["pos_in", "Получ. +"], ["neg_in", "Получ. −"],
    ["pos_out", "Отдал +"], ["neg_out", "Отдал −"], ["mutual_pos", "Взаимн. +"],
    ["status_pos", "Статус +"], ["status_neg", "Статус −"], ["status", "Свод. статус"],
    ["exp_pos", "Экспанс. +"], ["satisfaction", "Куд"], ["category", "Категория"],
  ];
  if (R.study.perceptual) cols.push(["accuracy_pos", "Точн. ожид. +"], ["awareness_pos", "Осознан. +"]);
  let sortKey = renderIndividual.key || "rank", dir = renderIndividual.dir || 1;
  const catOrder = { star: 0, preferred: 1, accepted: 2, neglected: 3, rejected: 4, isolated: 5 };
  const draw = () => {
    const rows = [...R.members].sort((a, b) => {
      let x = a[sortKey], y = b[sortKey];
      if (sortKey === "category") { x = catOrder[x]; y = catOrder[y]; }
      if (x === null) x = -Infinity; if (y === null) y = -Infinity;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
    });
    $("#ind").innerHTML = `<thead><tr>${cols.map(([k, l]) => `<th data-k="${k}">${l}${k === sortKey ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${cols.map(([k]) => {
        const v = r[k];
        if (k === "name") return `<td><a href="#/s/${S.id}/person/${r.id}">${esc(v)}</a></td>`;
        if (k === "category") return `<td><span class="badge b-${v}">${CAT[v]}</span></td>`;
        if (typeof v === "number" && !Number.isInteger(v)) return `<td>${fmt(v)}</td>`;
        if (["status_pos", "status_neg", "status", "exp_pos", "satisfaction", "accuracy_pos", "awareness_pos"].includes(k)) return `<td>${fmt(v)}</td>`;
        return `<td>${v ?? "—"}</td>`;
      }).join("")}</tr>`).join("")}</tbody>`;
    $$("#ind th").forEach((th) => (th.onclick = () => {
      if (sortKey === th.dataset.k) dir = -dir; else { sortKey = th.dataset.k; dir = th.dataset.k === "name" || th.dataset.k === "rank" || th.dataset.k === "category" ? 1 : -1; }
      renderIndividual.key = sortKey; renderIndividual.dir = dir;
      draw();
    }));
  };
  draw();
}

async function renderPerson(el, memberId) {
  const cid = currentCriterion();
  if (!cid) return renderResults(el);
  const R = await api("GET", `criteria/${cid}/results`);
  const member = R.members.find((m) => m.id === memberId);
  if (!member) {
    el.innerHTML = `<div class="panel empty">Участник не найден. <a href="#/s/${S.id}/results">Вернуться к отчёту</a></div>`;
    return;
  }
  const byId = Object.fromEntries(R.members.map((m) => [m.id, m]));
  const names = (kind, direction) => R.edges.filter((e) => e.kind === kind && e[direction] === memberId)
    .map((e) => esc(byId[direction === "source" ? e.target : e.source].name)).join(", ") || "нет";
  el.innerHTML = `<div class="row no-print"><a href="#/s/${S.id}/results">← Общий отчёт</a>
      <span class="grow"></span><button onclick="window.print()">Печать / PDF</button></div>
    <h2>${esc(member.name)}</h2>
    <div class="panel"><span class="badge b-${member.category}">${CAT[member.category]}</span>
      <span class="muted small"> · место в группе: ${member.rank}</span></div>
    <div class="stats">
      <div class="stat"><div class="v">${fmt(member.status_pos)}</div><div class="l">Положительный статус</div></div>
      <div class="stat"><div class="v">${fmt(member.status_neg)}</div><div class="l">Отрицательный статус</div></div>
      <div class="stat"><div class="v">${fmt(member.status)}</div><div class="l">Сводный статус</div></div>
      <div class="stat"><div class="v">${fmt(member.exp_pos + member.exp_neg)}</div><div class="l">Общая экспансивность</div></div>
      <div class="stat"><div class="v">${fmt(member.satisfaction)}</div><div class="l">Куд</div></div>
    </div>
    <h2>Выборы участника</h2>
    <div class="panel person-choices">
      <p><b>Выбрал (+):</b> ${names("pos", "source")}</p>
      <p><b>Выбрал (−):</b> ${names("neg", "source")}</p>
      <p><b>Получил (+):</b> ${names("pos", "target")}</p>
      <p><b>Получил (−):</b> ${names("neg", "target")}</p>
    </div>
    <h2>Связи в группе</h2><div class="graph-box" id="person-graph"></div>`;
  const graph = new Graph($("#person-graph"), R, "force");
  graph.highlight(graph.byId[memberId]);
}

// ------------------------------------------------------------------ sociogram
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
};

class Graph {
  constructor(box, R, layout, ref, initialShow = {}) {
    this.box = box; this.R = R; this.layout = layout;
    this.show = { pos: true, neg: true, mutualOnly: false, ...initialShow };
    this.layoutKey = this.show.mutualOnly ? "mutual" : layout;
    this.view = { x: 0, y: 0, k: 1 };
    this.W = 1000; this.H = 620;
    this.nodes = R.members.map((m) => ({ ...m, r: 9 + 4 * Math.sqrt(m.pos_in), x: 0, y: 0, vx: 0, vy: 0 }));
    this.byId = Object.fromEntries(this.nodes.map((n) => [n.id, n]));
    const set = new Set(R.edges.map((e) => e.kind + e.source + "-" + e.target));
    this.edges = [];
    for (const e of R.edges) {
      const mutual = set.has(e.kind + e.target + "-" + e.source);
      if (mutual && e.source > e.target) continue; // взаимную пару рисуем одной линией
      this.edges.push({ ...e, mutual, s: this.byId[e.source], t: this.byId[e.target] });
    }
    this.buildDom();
    const saved = R.layouts?.[this.layoutKey] || {};
    if (layout === "force") this.forceLayout(!Object.keys(saved).length);
    else this.targetLayout(ref);
    for (const n of this.nodes) {
      const point = saved[String(n.id)];
      if (point) { n.x = point[0]; n.y = point[1]; n.pinned = true; }
    }
    this.draw();
    this.fit();
  }

  buildDom() {
    this.box.innerHTML = "";
    const tools = document.createElement("div");
    tools.className = "graph-tools";
    const btn = (label, key) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.className = this.show[key] ? "on" : "";
      b.onclick = () => { this.show[key] = !this.show[key]; b.className = this.show[key] ? "on" : ""; this.draw(); };
      tools.appendChild(b);
    };
    btn("Выборы «+»", "pos"); btn("Выборы «−»", "neg"); btn("Только взаимные", "mutualOnly");
    const fit = document.createElement("button");
    fit.textContent = "Вписать";
    fit.onclick = () => { this.fit(); };
    tools.appendChild(fit);
    const saveSvg = document.createElement("button");
    saveSvg.textContent = "Скачать SVG";
    saveSvg.onclick = () => this.downloadSvg();
    tools.appendChild(saveSvg);
    const saveLayout = document.createElement("button");
    saveLayout.textContent = "Сохранить раскладку";
    saveLayout.onclick = async () => {
      const positions = Object.fromEntries(this.nodes.map((n) => [String(n.id), [Math.round(n.x), Math.round(n.y)]]));
      await api("POST", `criteria/${this.R.criterion.id}/layout/${this.layoutKey}`, positions);
      this.R.layouts[this.layoutKey] = positions;
      toast("Раскладка сохранена локально");
    };
    tools.appendChild(saveLayout);
    if (this.layout === "force") {
      const re = document.createElement("button");
      re.textContent = "Перестроить";
      re.onclick = () => { this.nodes.forEach((n) => { n.pinned = false; }); this.forceLayout(true); };
      tools.appendChild(re);
    }
    this.box.appendChild(tools);

    const svg = svgEl("svg", { viewBox: `0 0 ${this.W} ${this.H}` });
    const defs = svgEl("defs");
    const uid = Math.random().toString(36).slice(2, 7);
    this.mk = {};
    for (const [k, color] of [["pos", "#4f8a10"], ["neg", "#e2622f"]]) {
      for (const dir of ["end", "start"]) {
        const id = `m-${k}-${dir}-${uid}`;
        const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: dir === "end" ? "auto" : "auto-start-reverse", markerUnits: "userSpaceOnUse" });
        m.setAttribute("markerWidth", 10); m.setAttribute("markerHeight", 10);
        m.appendChild(svgEl("path", { d: "M0,1 L10,5 L0,9 z", fill: color }));
        defs.appendChild(m);
        this.mk[k + dir] = id;
      }
    }
    svg.appendChild(defs);
    this.bg = svgEl("g");
    this.vp = svgEl("g");
    this.vp.appendChild(this.bg);
    this.gEdges = svgEl("g"); this.gNodes = svgEl("g");
    this.vp.appendChild(this.gEdges); this.vp.appendChild(this.gNodes);
    svg.appendChild(this.vp);
    this.box.appendChild(svg);
    this.svg = svg;

    for (const e of this.edges) {
      e.el = svgEl("line", { class: "edge" });
      this.gEdges.appendChild(e.el);
    }
    for (const n of this.nodes) {
      const g = svgEl("g", { class: "node" });
      const c = svgEl("circle", { r: n.r, fill: CAT_COLOR[n.category] });
      const t = svgEl("text", { y: n.r + 13, "text-anchor": "middle" });
      t.textContent = n.name;
      const title = svgEl("title");
      title.textContent = `${n.name}\n${CAT[n.category]}\nполучено: +${n.pos_in} / −${n.neg_in}\nотдано: +${n.pos_out} / −${n.neg_out}\nвзаимных «+»: ${n.mutual_pos}`;
      c.appendChild(title);
      g.appendChild(c);
      if (n.has_photo) {
        const clipId = `photo-${n.id}-${uid}`;
        const clip = svgEl("clipPath", { id: clipId });
        clip.appendChild(svgEl("circle", { r: n.r - 2 }));
        defs.appendChild(clip);
        g.appendChild(svgEl("image", { href: `/api/members/${n.id}/photo`, x: -n.r + 2, y: -n.r + 2,
          width: 2 * (n.r - 2), height: 2 * (n.r - 2), "clip-path": `url(#${clipId})`,
          preserveAspectRatio: "xMidYMid slice", "pointer-events": "none" }));
      }
      g.appendChild(t);
      this.gNodes.appendChild(g);
      n.el = g;
      g.addEventListener("mouseenter", () => this.highlight(n));
      g.addEventListener("mouseleave", () => this.highlight(null));
    }
    this.bindPointer();
  }

  toLocal(evt) {
    const pt = this.svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const p = pt.matrixTransform(this.svg.getScreenCTM().inverse());
    return { x: (p.x - this.view.x) / this.view.k, y: (p.y - this.view.y) / this.view.k, sx: p.x, sy: p.y };
  }

  bindPointer() {
    let drag = null;
    this.svg.addEventListener("pointerdown", (e) => {
      const g = e.target.closest(".node");
      const p = this.toLocal(e);
      if (g) {
        const n = this.nodes.find((n) => n.el === g);
        drag = { node: n, dx: n.x - p.x, dy: n.y - p.y };
      } else {
        drag = { pan: true, sx: p.sx, sy: p.sy, vx: this.view.x, vy: this.view.y };
      }
      this.svg.setPointerCapture(e.pointerId);
      this.svg.classList.add("dragging");
    });
    this.svg.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const p = this.toLocal(e);
      if (drag.node) {
        drag.node.x = p.x + drag.dx; drag.node.y = p.y + drag.dy; drag.node.pinned = true;
        drag.node.vx = drag.node.vy = 0;
        this.draw();
      } else {
        this.view.x = drag.vx + (p.sx - drag.sx); this.view.y = drag.vy + (p.sy - drag.sy);
        this.applyView();
      }
    });
    const end = () => { drag = null; this.svg.classList.remove("dragging"); };
    this.svg.addEventListener("pointerup", end);
    this.svg.addEventListener("pointercancel", end);
    this.svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const p = this.toLocal(e);
      const k = Math.min(5, Math.max(0.2, this.view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      this.view.x = p.sx - p.x * k; this.view.y = p.sy - p.y * k; this.view.k = k;
      this.applyView();
    }, { passive: false });
  }

  applyView() {
    this.vp.setAttribute("transform", `translate(${this.view.x},${this.view.y}) scale(${this.view.k})`);
  }

  async downloadSvg() {
    const copy = this.svg.cloneNode(true);
    copy.setAttribute("xmlns", SVGNS);
    copy.setAttribute("width", this.W);
    copy.setAttribute("height", this.H);
    const style = svgEl("style");
    style.textContent = ".node text{font:12px sans-serif;paint-order:stroke;stroke:white;stroke-width:3px}.node circle{stroke:#15181e;stroke-opacity:.25;stroke-width:1.5}.dim{opacity:.12}";
    copy.prepend(style);
    for (const picture of copy.querySelectorAll("image")) {
      const response = await fetch(picture.getAttribute("href"));
      const blob = await response.blob();
      const dataUrl = await new Promise((resolve) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsDataURL(blob);
      });
      picture.setAttribute("href", dataUrl);
    }
    const blob = new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = `${S.name} - ${this.layout === "target" ? "мишень" : "социограмма"}.svg`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  fit() {
    if (!this.nodes.length) return;
    const pad = 60;
    const xs = this.nodes.map((n) => n.x), ys = this.nodes.map((n) => n.y);
    let x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    if (this.layout === "target") { x0 = -this.Rmax - 40; x1 = this.Rmax + 40; y0 = -this.Rmax - 40; y1 = this.Rmax + 40; }
    const k = Math.min(this.W / (x1 - x0), this.H / (y1 - y0), 1.25);
    this.view = { k, x: (this.W - (x0 + x1) * k) / 2, y: (this.H - (y0 + y1) * k) / 2 };
    this.applyView();
  }

  highlight(n) {
    if (!n) {
      this.nodes.forEach((x) => x.el.classList.remove("dim"));
      this.edges.forEach((e) => e.el.classList.remove("dim"));
      return;
    }
    const near = new Set([n.id]);
    for (const e of this.edges) if (e.el.style.display !== "none" && (e.s === n || e.t === n)) { near.add(e.s.id); near.add(e.t.id); }
    this.nodes.forEach((x) => x.el.classList.toggle("dim", !near.has(x.id)));
    this.edges.forEach((e) => e.el.classList.toggle("dim", !(e.s === n || e.t === n)));
  }

  forceLayout(animate = true) {
    const N = this.nodes.length;
    const R0 = 40 + 22 * Math.sqrt(N);
    this.nodes.forEach((n, i) => {
      const a = (2 * Math.PI * i) / N;
      n.x = R0 * Math.cos(a) + (Math.random() - 0.5) * 10;
      n.y = R0 * Math.sin(a) + (Math.random() - 0.5) * 10;
      n.vx = n.vy = 0;
    });
    let alpha = 1;
    const step = () => {
      const ns = this.nodes;
      for (let i = 0; i < ns.length; i++) {
        for (let j = i + 1; j < ns.length; j++) {
          const a = ns[i], b = ns[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
          const d = Math.sqrt(d2);
          const f = (5000 / d2) * alpha;
          a.vx -= (dx / d) * f; a.vy -= (dy / d) * f; b.vx += (dx / d) * f; b.vy += (dy / d) * f;
        }
      }
      for (const e of this.edges) {
        const a = e.s, b = e.t;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
        const rest = e.kind === "pos" ? (e.mutual ? 70 : 110) : 260;
        const k = e.kind === "pos" ? (e.mutual ? 0.06 : 0.03) : 0.006;
        const f = (d - rest) * k * alpha;
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
      for (const n of ns) {
        n.vx -= n.x * 0.01 * alpha; n.vy -= n.y * 0.01 * alpha;
        if (n.pinned) { n.vx = n.vy = 0; continue; }
        n.vx *= 0.6; n.vy *= 0.6;
        n.x += Math.max(-30, Math.min(30, n.vx)); n.y += Math.max(-30, Math.min(30, n.vy));
      }
      alpha *= 0.985;
    };
    // основную часть раскладки считаем сразу, остаток — анимацией
    for (let i = 0; i < 220; i++) step();
    this.fit(); this.draw();
    if (!animate) return;
    let frames = 0;
    const tick = () => {
      step(); this.draw();
      if (++frames < 90 && alpha > 0.02) requestAnimationFrame(tick);
      else this.fit();
    };
    requestAnimationFrame(tick);
  }

  targetLayout(ref) {
    const rings = { star: 0, preferred: 1, accepted: 2, neglected: 3, isolated: 3, rejected: 3 };
    const step = 85;
    this.Rmax = step * 3.5 + 30;
    for (let i = 0; i < 4; i++) {
      this.bg.appendChild(svgEl("circle", { cx: 0, cy: 0, r: step * (i + 0.5) + 30, fill: i % 2 ? "#fafbfa" : "#f1f6f3", stroke: "#dde2de" }));
    }
    // рисуем от внешнего к внутреннему, чтобы внутренний круг был сверху
    const circles = [...this.bg.children].reverse();
    this.bg.innerHTML = "";
    circles.forEach((c) => this.bg.appendChild(c));
    ["звёзды", "предпочитаемые", "принятые", "изолир. / отвергнутые"].forEach((label, i) => {
      const t = svgEl("text", { x: 0, y: -(step * (i + 0.5) + 30) + 14, "text-anchor": "middle", fill: "#9aa49e", "font-size": 11 });
      t.textContent = label;
      this.bg.appendChild(t);
    });
    // угол берём из силовой раскладки, чтобы группировки сохранялись рядом
    const angle = (n) => {
      const r = ref && ref.byId[n.id];
      return r ? Math.atan2(r.y, r.x) : 0;
    };
    for (let ring = 0; ring < 4; ring++) {
      const list = this.nodes.filter((n) => rings[n.category] === ring).sort((a, b) => angle(a) - angle(b));
      const rad = ring === 0 ? (list.length === 1 ? 0 : 35) : step * ring + 30;
      const offset = list.length ? angle(list[0]) : 0;
      list.forEach((n, i) => {
        const a = offset + (2 * Math.PI * i) / list.length;
        n.x = rad * Math.cos(a); n.y = rad * Math.sin(a);
      });
    }
    this.draw();
  }

  draw() {
    for (const e of this.edges) {
      const visible = this.show[e.kind] && (!this.show.mutualOnly || e.mutual);
      e.el.style.display = visible ? "" : "none";
      if (!visible) continue;
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / d, uy = dy / d;
      const x1 = e.s.x + ux * (e.s.r + (e.mutual ? 3 : 1)), y1 = e.s.y + uy * (e.s.r + (e.mutual ? 3 : 1));
      const x2 = e.t.x - ux * (e.t.r + 3), y2 = e.t.y - uy * (e.t.r + 3);
      const color = e.kind === "pos" ? "#4f8a10" : "#e2622f";
      e.el.setAttribute("x1", x1); e.el.setAttribute("y1", y1);
      e.el.setAttribute("x2", x2); e.el.setAttribute("y2", y2);
      e.el.setAttribute("stroke", color);
      e.el.setAttribute("stroke-width", e.mutual ? 3.2 : 1.4);
      e.el.setAttribute("stroke-opacity", e.kind === "pos" ? 0.85 : 0.7);
      if (e.kind === "neg") e.el.setAttribute("stroke-dasharray", "6 4");
      e.el.setAttribute("marker-end", `url(#${this.mk[e.kind + "end"]})`);
      if (e.mutual) e.el.setAttribute("marker-start", `url(#${this.mk[e.kind + "start"]})`);
    }
    for (const n of this.nodes) n.el.setAttribute("transform", `translate(${n.x},${n.y})`);
  }
}

// ------------------------------------------------------------------ help
function renderHelp() {
  app.innerHTML = `<div class="help">
  <h1>Справка</h1>
  <div class="panel">
  <h2 style="margin-top:0">Как провести социометрию</h2>
  <ol>
    <li><b>Создайте социометрию</b>: название группы, список участников (можно вставить столбец из Excel) и один или несколько критериев —
      вопросов вида «С кем бы вы хотели работать вместе?».</li>
    <li><b>Проведите опрос</b> на бумаге или устно: каждый участник называет тех, кого выбирает (+), и, если нужно, тех, кого не выбрал бы (−).
      Лимит выборов задаётся в настройках, например по 3.</li>
    <li><b>Внесите ответы</b> на вкладке «Ввод выборов»: строка — кто выбирает, столбец — кого. Щелчок по ячейке переключает пусто → + → −.
      Всё сохраняется сразу, кнопка «Сохранить» не нужна.</li>
    <li><b>Смотрите результаты</b>: групповые индексы, статусы участников, социограммы и социоматрицу. Их можно распечатать или сохранить в PDF
      через «Печать», а таблицы выгрузить в CSV для Excel.</li>
  </ol>
  <p>На вкладке «Результаты» диаграмма «Статусы в группе» показывает доли статусных категорий. Выберите Plotly или Matplotlib
  через checkbox, затем нажмите сектор или название категории, чтобы увидеть участников. Plotly сохраняет SVG или PNG 300 DPI,
  Matplotlib — PNG 300 DPI. Все графики строятся на вашем компьютере.</p>
  <h2>Перцептивные выборы</h2>
  <p>Если включить их в настройках, в режиме «Перцептивные» для каждого участника отмечается, кто, по его мнению, выбрал его (п+) или отверг (п−).
  Программа считает, насколько ожидания совпали с реальностью: <i>точность ожиданий</i> (сколько из ожидаемых действительно выбрали)
  и <i>осознанность</i> (какую долю реально полученных выборов участник угадал).</p>
  <h2>Загрузка из файла</h2>
  <p>Поддерживаются .xls, .xlsx и .csv (разделитель «;» или «,»). Список участников — один столбец с ФИО или два столбца «№» и «ФИО».
  Готовая матрица выборов в формате сайта — столбцы «№», «ФИО», затем номера участников; в ячейках «+»/«1» и «−»/«-1».
  Также принимается матрица с ФИО в первой строке и первом столбце.
  При создании отметьте «Файл уже содержит выборы». <a href="/templates/participants.xlsx" download>Пример списка</a> ·
  <a href="/templates/choices.xlsx" download>Пример матрицы</a>.</p>
  <h2>Формулы</h2>
  <ul>
    <li><b>N</b> — число участников; <b>R+</b>, <b>R−</b> — полученные положительные и отрицательные выборы.</li>
    <li>Социометрический статус: <code>C+ = R+ / (N−1)</code>, <code>C− = R− / (N−1)</code>, сводный <code>(R+ − R−) / (N−1)</code>.</li>
    <li>Эмоциональная экспансивность участника: <code>отдано выборов / (N−1)</code>; группы — среднее число всех выборов на человека.</li>
    <li>Коэффициент удовлетворённости в отчёте: <code>Куд = получено «+» / отдано «+»</code>.</li>
    <li>Сплочённость группы: <code>взаимные пары «+» / (N·(N−1)/2)</code>; конфликтность — то же для взаимных «−».</li>
    <li>Референтность группы: <code>взаимные пары «+» / все положительные выборы</code>.</li>
    <li>Доля взаимных выборов: <code>2 · взаимные пары «+» / все «+» выборы</code>.</li>
    <li>Напряжённость: доля отрицательных выборов среди всех.</li>
    <li>КБВ (коэффициент благополучия взаимоотношений): доля звёзд и предпочитаемых; индекс изолированности — доля изолированных и отвергнутых.</li>
    <li>Статусные категории считаются от среднего (M) полученных «+»: звезда — от 2M, предпочитаемый — от 1,5M при малом числе «−»,
      пренебрегаемый — мало «+» или много «−», отвергаемый — мало «+» при наличии «−», изолированный — нет полученных выборов.
      Оптимистичный режим учитывает положительные выборы при отнесении к низким статусным группам.</li>
  </ul>
  <h2>Где хранятся данные</h2>
  <p>В приложении macOS база находится в <code>~/Library/Application Support/OpenSociometry/sociometry.db</code>.
  Её папку можно открыть из меню OpenSociometry → «Открыть папку данных». При обновлении приложения база сохраняется.
  В переносимом пакете Windows и при запуске из исходников используется <code>data/sociometry.db</code> в папке программы.
  Чтобы перенести данные, закройте программу и скопируйте базу или скачайте резервную копию социометрии (.json)
  на вкладке «Участники и критерии», затем восстановите её на главной странице.</p>
  </div></div>`;
}
