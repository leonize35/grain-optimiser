// Silo Optimiser builder, slice 9a: site and systems, equipment, grain connections, check, save and versions, run.
// The app holds no engine rules: equipment types, fields and allowed connections come from GET /meta, every check
// from POST /validate (the engine's pre-run report), and every result from a run of a saved version.

const S = {
  meta: null,
  config: null,        // the draft being edited
  saved: null,         // {site_id, version, config_hash} of the version the draft started from, or null
  dirty: false,
  report: null,        // last pre-run report of the draft
  selected: null,      // selected equipment id
  runs: [],            // runs started in this browser session
  example: null,       // label when the draft came from a synthetic example
};

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (x) => JSON.parse(JSON.stringify(x));
const num = (v) => (v === "" || v === null || v === undefined ? undefined : Number(v));

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d : d && d.messages ? d.message + " " + d.messages.join("; ") : d && d.message ? d.message : `HTTP ${r.status}`;
    const err = new Error(msg); err.status = r.status; err.detail = d; throw err;
  }
  return data;
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 3200);
}

function markDirty() {
  S.dirty = true; S.report = null; header(); scheduleCheck();
}

let checkTimer = null;
function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 500);
}

async function runCheck() {
  if (!S.config) return;
  try { S.report = await api("POST", "/validate", S.config); }
  catch (e) { S.report = { ok: false, errors: 1, warnings: 0, notes: 0, unreadable: true, findings: [{ code: "schema", severity: "error", source: "schema", message: e.message, location: [], fix: "Correct the field named in the message.", systems: [] }] }; }
  header();
  if (["check", "equipment", "connections"].includes(current())) render();  // issue counts follow the check
}

function header() {
  const c = S.config;
  $("#site-name").textContent = c ? (c.name || c.id) : "No silo open";
  $("#site-sub").textContent = c
    ? `Site id ${c.id}` + (S.saved ? ` · from saved version ${S.saved.version}` : " · not saved yet") + (S.example ? ` · started from ${S.example} (synthetic example)` : "")
    : "Open a saved silo, start from an example, or create a new one.";
  const bs = $("#badge-save");
  bs.textContent = !c ? "Not saved" : S.dirty ? "Unsaved changes" : S.saved ? `Saved (v${S.saved.version})` : "Not saved";
  bs.className = "badge " + (c && S.dirty ? "warn" : c && S.saved ? "good" : "");
  const bc = $("#badge-check"), r = S.report;
  bc.textContent = !c ? "Not checked" : !r ? "Checking…" : r.ok ? (r.warnings ? `Can run · ${r.warnings} warning(s)` : "Can run") : `${r.errors} error(s)`;
  bc.className = "badge " + (!c || !r ? "" : r.ok ? (r.warnings ? "warn" : "good") : "error");
}

function current() { return (location.hash || "#silo").slice(1); }

function eqById(id) { return S.config.equipment.find((e) => e.id === id); }
function systemOf(id) { const s = (S.config.systems || []).find((x) => x.equipment.includes(id)); return s ? s.id : ""; }
function typeLabel(t) { return S.meta.equipment_types[t] ? S.meta.equipment_types[t].label : t; }
function nameOf(id) { const e = eqById(id); return e ? (e.name || e.id) : id; }

function newId(prefix) {
  let n = 1; while (S.config.equipment.some((e) => e.id === `${prefix}${n}`)) n++; return `${prefix}${n}`;
}
const PREFIX = { sampler: "S", grader: "G", weighbridge: "WB", hopper: "H", conveyor: "C", elevator: "E", bin: "B", loadpoint: "L" };

function blankSite() {
  return { id: "my-silo", name: "My silo", version: 1, hours: { open: 7, close: 18 },
    commodities: [{ id: "YM", name: "Yellow maize" }], equipment: [], edges: [], systems: [],
    sequences: { unload: ["weigh_in", "tip", "weigh_out"], load: [], weigh: [] }, demand: {} };
}

function guard() { return !S.dirty || confirm("You have unsaved changes. Discard them?"); }

function open(config, saved, example) {
  S.config = clone(config); S.config.systems = S.config.systems || [];
  S.saved = saved; S.example = example || null; S.dirty = !saved; S.selected = null; S.report = null;
  header(); runCheck(); location.hash = "#equipment"; render();
}

// ---------- screens ----------
const screens = {};

screens.silo = async () => {
  const [sites, examples] = await Promise.all([api("GET", "/sites"), api("GET", "/examples")]);
  const c = S.config;
  let html = `<h1>My silo</h1><p class="lead">Start here: open a saved silo, start from a synthetic example, or create a new one. Then describe its systems, commodities and opening hours.</p>`;
  html += `<div class="grid2"><div class="card"><h2>Open or start</h2>
    <label for="open-site">Saved silos</label>
    <select id="open-site" class="wide"><option value="">${sites.length ? "Choose…" : "None saved yet"}</option>${sites.map((s) => `<option>${esc(s)}</option>`).join("")}</select>
    <label for="open-example">Synthetic examples (not real sites)</label>
    <select id="open-example" class="wide"><option value="">Choose…</option>${examples.map((e) => `<option value="${esc(e.file)}" title="${esc(e.note)}">${esc(e.label)}</option>`).join("")}</select>
    <div class="actions"><button id="btn-open">Open</button><button id="btn-new">New empty silo</button></div></div>`;
  if (c) {
    html += `<div class="card"><h2>Site</h2>
      <label for="f-name">Site name</label><input id="f-name" class="wide" value="${esc(c.name)}">
      <label for="f-id">Site id (letters, digits, - _ .)</label><input id="f-id" class="wide" value="${esc(c.id)}">
      <label>Opening hours (decimal hours, e.g. 7.5 = 07:30)</label>
      <div class="tri"><span class="unit">open</span><input id="f-open" type="number" step="0.1" value="${esc(c.hours.open)}">
      <span class="unit">admission cut-off</span><input id="f-cutoff" type="number" step="0.1" value="${esc(c.hours.admission_cutoff ?? "")}" placeholder="= close">
      <span class="unit">close</span><input id="f-close" type="number" step="0.1" value="${esc(c.hours.close)}">
      <span class="unit">overtime h</span><input id="f-overtime" type="number" step="0.1" value="${esc(c.hours.overtime ?? 0)}"></div></div>`;
  }
  html += `</div>`;
  if (c) {
    html += `<div class="grid2"><div class="card"><h2>Silo systems</h2><p class="muted small">Group equipment into systems such as "Silo A" and "Silo B". Equipment in no system is shared. Grouping changes reporting only, never how trucks or grain move.</p>
      <table><thead><tr><th>Id</th><th>Name</th><th>Equipment</th><th></th></tr></thead><tbody>
      ${c.systems.map((s, i) => `<tr><td><input data-sys-id="${i}" value="${esc(s.id)}" size="6"></td><td><input data-sys-name="${i}" value="${esc(s.name)}"></td><td class="small">${s.equipment.length}</td><td><button class="danger" data-sys-del="${i}">Remove</button></td></tr>`).join("") || `<tr><td colspan="4" class="muted">No systems yet: everything is site-level.</td></tr>`}
      </tbody></table><div class="actions"><button id="btn-add-sys">Add system</button></div></div>
      <div class="card"><h2>Commodities</h2>
      <table><thead><tr><th>Id</th><th>Name</th><th></th></tr></thead><tbody>
      ${c.commodities.map((m, i) => `<tr><td><input data-com-id="${i}" value="${esc(m.id)}" size="6"></td><td><input data-com-name="${i}" value="${esc(m.name)}"></td><td><button class="danger" data-com-del="${i}">Remove</button></td></tr>`).join("")}
      </tbody></table><div class="actions"><button id="btn-add-com">Add commodity</button></div></div></div>`;
  }
  $("#main").innerHTML = html;
  $("#btn-open").onclick = async () => {
    const site = $("#open-site").value, ex = $("#open-example").value;
    if (!site && !ex) return toast("Choose a saved silo or an example.");
    if (!guard()) return;
    if (site) {
      const cfg = await api("GET", `/sites/${encodeURIComponent(site)}`);
      const h = await api("GET", `/sites/${encodeURIComponent(site)}/history`);
      const last = h[h.length - 1];
      open(cfg, { site_id: site, version: last.version, config_hash: last.config_hash });
    } else {
      const cfg = await api("GET", `/examples/${encodeURIComponent(ex)}`);
      open(cfg, null, $("#open-example").selectedOptions[0].textContent);
    }
  };
  $("#btn-new").onclick = () => { if (guard()) open(blankSite(), null); };
  if (!c) return;
  const bind = (id, fn) => { const el = $(id); el.onchange = () => { fn(el.value); markDirty(); }; };
  bind("#f-name", (v) => { c.name = v; });
  bind("#f-id", (v) => { c.id = v.trim(); });
  bind("#f-open", (v) => { c.hours.open = num(v); });
  bind("#f-close", (v) => { c.hours.close = num(v); });
  bind("#f-overtime", (v) => { c.hours.overtime = num(v) || 0; });
  bind("#f-cutoff", (v) => { if (v === "") delete c.hours.admission_cutoff; else c.hours.admission_cutoff = num(v); });
  document.querySelectorAll("[data-sys-id]").forEach((el) => { el.onchange = () => { c.systems[+el.dataset.sysId].id = el.value.trim(); markDirty(); }; });
  document.querySelectorAll("[data-sys-name]").forEach((el) => { el.onchange = () => { c.systems[+el.dataset.sysName].name = el.value; markDirty(); }; });
  document.querySelectorAll("[data-sys-del]").forEach((el) => { el.onclick = () => { c.systems.splice(+el.dataset.sysDel, 1); markDirty(); render(); }; });
  $("#btn-add-sys").onclick = () => { const n = c.systems.length + 1; c.systems.push({ id: `SYS${n}`, name: `Silo ${String.fromCharCode(64 + n)}`, equipment: [] }); markDirty(); render(); };
  document.querySelectorAll("[data-com-id]").forEach((el) => { el.onchange = () => { c.commodities[+el.dataset.comId].id = el.value.trim(); markDirty(); }; });
  document.querySelectorAll("[data-com-name]").forEach((el) => { el.onchange = () => { c.commodities[+el.dataset.comName].name = el.value; markDirty(); }; });
  document.querySelectorAll("[data-com-del]").forEach((el) => { el.onclick = () => { c.commodities.splice(+el.dataset.comDel, 1); markDirty(); render(); }; });
  $("#btn-add-com").onclick = () => { c.commodities.push({ id: `C${c.commodities.length + 1}`, name: "New commodity" }); markDirty(); render(); };
};

function needSite() {
  if (S.config) return false;
  $("#main").innerHTML = `<h1>${esc(current())}</h1><div class="card"><p>No silo is open. <a href="#silo">Open or create one</a> first.</p></div>`;
  return true;
}

function issuesFor(id) {
  return (S.report ? S.report.findings : []).filter((f) => f.location.includes(id) && f.severity !== "note");
}

function fieldInput(e, f) {
  const v = e[f.name], id = `fld-${f.name}`, req = f.required ? ` <span class="req" title="required">*</span>` : "";
  const unit = f.unit ? ` <span class="unit">${esc(f.unit)}</span>` : "";
  const help = f.help ? `<div class="muted small">${esc(f.help)}</div>` : "";
  const label = `<label for="${id}">${esc(f.label)}${req}</label>`;
  if (f.kind === "number" || f.kind === "integer")
    return `${label}<input id="${id}" type="number" step="${f.kind === "integer" ? 1 : "any"}" data-field="${f.name}" data-kind="${f.kind}" value="${esc(v ?? "")}">${unit}${help}`;
  if (f.kind === "triangular") {
    const t = Array.isArray(v) ? v : ["", "", ""];
    return `${label}<div class="tri">${[0, 1, 2].map((i) => `<input type="number" step="any" aria-label="${esc(f.label)} ${["minimum", "most likely", "maximum"][i]}" data-tri="${f.name}" data-i="${i}" value="${esc(t[i] ?? "")}">`).join("")}${unit}</div>${help}`;
  }
  if (f.kind === "choice")
    return `${label}<select id="${id}" data-field="${f.name}" data-kind="choice"><option value="">(default)</option>${f.options.map((o) => `<option ${v === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>${help}`;
  if (f.kind === "commodity")
    return `${label}<select id="${id}" data-field="${f.name}" data-kind="choice"><option value="">(none)</option>${S.config.commodities.map((c) => `<option value="${esc(c.id)}" ${v === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>${help}`;
  if (f.kind === "commodities" || f.kind === "activities") {
    const opts = f.kind === "commodities" ? S.config.commodities.map((c) => [c.id, c.name]) : S.meta.activities.map((a) => [a.id, a.label]);
    const set = new Set(v || []);
    return `${label}<div>${opts.map(([oid, oname]) => `<label style="display:inline-flex;gap:4px;margin-right:12px;color:var(--text)"><input type="checkbox" data-multi="${f.name}" value="${esc(oid)}" ${set.has(oid) ? "checked" : ""}>${esc(oname)}</label>`).join("")}</div>${help}`;
  }
  return "";
}

screens.equipment = () => {
  if (needSite()) return;
  const c = S.config, types = S.meta.equipment_types;
  const groups = [...c.systems.map((s) => [s.id, s.name]), ["", "Shared / site-level"]];
  let rows = "";
  for (const [gid, gname] of groups) {
    const items = c.equipment.filter((e) => systemOf(e.id) === gid);
    if (!items.length && gid) { rows += `<tr><td colspan="4" class="group">${esc(gname)} <span class="muted small">(empty)</span></td></tr>`; continue; }
    if (!items.length) continue;
    rows += `<tr><td colspan="4" class="group">${esc(gname)}</td></tr>`;
    rows += items.map((e) => { const n = issuesFor(e.id).length; return `<tr class="clickable ${S.selected === e.id ? "selected" : ""}" data-select="${esc(e.id)}"><td>${esc(e.id)}</td><td>${esc(e.name || "")}</td><td>${esc(typeLabel(e.type))}</td><td>${n ? `<span class="badge error">${n}</span>` : ""}</td></tr>`; }).join("");
  }
  const e = S.selected && eqById(S.selected);
  let form = `<div class="card"><h2>Properties</h2><p class="muted">Select equipment in the list, or add one from the palette.</p></div>`;
  if (e) {
    const t = types[e.type];
    const iss = issuesFor(e.id);
    form = `<div class="card"><h2>${esc(typeLabel(e.type))}: ${esc(e.name || e.id)}</h2>
      ${iss.map((f) => `<div class="finding ${f.severity}"><span class="sev">${f.severity}</span> ${esc(f.message)}${f.fix ? `<div class="fix">${esc(f.fix)}</div>` : ""}</div>`).join("")}
      <label for="eq-id">Id</label><input id="eq-id" value="${esc(e.id)}">
      <label for="eq-name">Name</label><input id="eq-name" class="wide" value="${esc(e.name || "")}">
      <label for="eq-sys">System</label><select id="eq-sys"><option value="">Shared / site-level</option>${c.systems.map((s) => `<option value="${esc(s.id)}" ${systemOf(e.id) === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
      ${t ? t.fields.map((f) => fieldInput(e, f)).join("") : `<p class="muted">Unsupported type ${esc(e.type)}.</p>`}
      <div class="actions"><button class="danger" id="eq-del">Remove ${esc(e.id)} and its connections</button></div></div>`;
  }
  $("#main").innerHTML = `<h1>Equipment</h1><p class="lead">Add the equipment of each silo system. Required fields are marked <span class="req">*</span>; the check updates as you type.</p>
    <div class="card"><h2>Add equipment</h2><div class="palette">${Object.entries(types).map(([t, info]) => `<button data-add="${t}">+ ${esc(info.label)}</button>`).join("")}</div></div>
    <div class="grid2"><div class="card"><h2>All equipment</h2><table><thead><tr><th>Id</th><th>Name</th><th>Type</th><th>Issues</th></tr></thead><tbody>${rows || `<tr><td colspan="4" class="muted">No equipment yet.</td></tr>`}</tbody></table></div>${form}</div>`;
  document.querySelectorAll("[data-add]").forEach((b) => { b.onclick = () => {
    const t = b.dataset.add, id = newId(PREFIX[t] || "X");
    c.equipment.push({ id, type: t, name: `${typeLabel(t)} ${id}` });
    S.selected = id; markDirty(); render();
  }; });
  document.querySelectorAll("[data-select]").forEach((r) => { r.onclick = () => { S.selected = r.dataset.select; render(); }; });
  if (!e) return;
  $("#eq-name").onchange = (ev) => { e.name = ev.target.value; markDirty(); render(); };
  $("#eq-id").onchange = (ev) => {
    const nid = ev.target.value.trim(), old = e.id;
    if (!nid || c.equipment.some((x) => x.id === nid)) { toast("That id is empty or already used."); return render(); }
    e.id = nid; c.edges = c.edges.map(([a, b]) => [a === old ? nid : a, b === old ? nid : b]);
    c.systems.forEach((s) => { s.equipment = s.equipment.map((x) => (x === old ? nid : x)); });
    S.selected = nid; markDirty(); render();
  };
  $("#eq-sys").onchange = (ev) => {
    c.systems.forEach((s) => { s.equipment = s.equipment.filter((x) => x !== e.id); });
    const s = c.systems.find((x) => x.id === ev.target.value); if (s) s.equipment.push(e.id);
    markDirty(); render();
  };
  $("#eq-del").onclick = () => {
    if (!confirm(`Remove ${e.id} and every connection to or from it?`)) return;
    c.equipment = c.equipment.filter((x) => x !== e); c.edges = c.edges.filter(([a, b]) => a !== e.id && b !== e.id);
    c.systems.forEach((s) => { s.equipment = s.equipment.filter((x) => x !== e.id); });
    S.selected = null; markDirty(); render();
  };
  document.querySelectorAll("[data-field]").forEach((el) => { el.onchange = () => {
    const k = el.dataset.field;
    if (el.value === "") delete e[k]; else e[k] = el.dataset.kind === "choice" ? el.value : num(el.value);
    markDirty();
  }; });
  document.querySelectorAll("[data-tri]").forEach((el) => { el.onchange = () => {
    const k = el.dataset.tri, vals = [...document.querySelectorAll(`[data-tri="${k}"]`)].map((x) => x.value);
    if (vals.every((x) => x === "")) delete e[k]; else e[k] = vals.map((x) => (x === "" ? 0 : Number(x)));
    markDirty();
  }; });
  document.querySelectorAll("[data-multi]").forEach((el) => { el.onchange = () => {
    const k = el.dataset.multi, vals = [...document.querySelectorAll(`[data-multi="${k}"]:checked`)].map((x) => x.value);
    if (vals.length) e[k] = vals; else delete e[k];
    markDirty();
  }; });
};

screens.connections = () => {
  if (needSite()) return;
  const c = S.config, types = S.meta.equipment_types;
  const sources = c.equipment.filter((e) => types[e.type] && types[e.type].connects_to.length);
  const from = $("#cx-from") ? $("#cx-from").value : "";
  const fromEq = eqById(from) || sources[0];
  const allowed = fromEq ? types[fromEq.type].connects_to : [];
  const targets = c.equipment.filter((e) => fromEq && allowed.includes(e.type) && e.id !== fromEq.id && !c.edges.some(([a, b]) => a === fromEq.id && b === e.id));
  const unreachable = (S.report ? S.report.findings : []).filter((f) => f.severity !== "note" && /route|reach|connect|feed|loop/i.test(f.message));
  $("#main").innerHTML = `<h1>Grain connections</h1><p class="lead">Grain moves only along the connections listed here, in the direction shown. Only connections the engine allows between equipment types can be added.</p>
    <div class="grid2"><div class="card"><h2>Add a connection</h2>
      <label for="cx-from">From</label><select id="cx-from" class="wide">${sources.map((e) => `<option value="${esc(e.id)}" ${fromEq && fromEq.id === e.id ? "selected" : ""}>${esc(e.name || e.id)} (${esc(typeLabel(e.type))})</option>`).join("")}</select>
      <p class="muted small">${fromEq ? `A ${esc(typeLabel(fromEq.type).toLowerCase())} may feed: ${allowed.map((t) => esc(typeLabel(t))).join(", ")}.` : "Add equipment first."}</p>
      <label for="cx-to">To</label><select id="cx-to" class="wide">${targets.map((e) => `<option value="${esc(e.id)}">${esc(e.name || e.id)} (${esc(typeLabel(e.type))})</option>`).join("") || `<option value="">No allowed target</option>`}</select>
      <div class="actions"><button class="primary" id="cx-add" ${targets.length ? "" : "disabled"}>Add connection</button></div></div>
      <div class="card"><h2>Route problems</h2>${unreachable.map((f) => `<div class="finding ${f.severity}"><span class="sev">${f.severity}</span> ${esc(f.message)}</div>`).join("") || `<p class="muted">${S.report ? "None found." : "Checking…"}</p>`}</div></div>
    <div class="card"><h2>Connections (${c.edges.length})</h2><table><thead><tr><th>From</th><th></th><th>To</th><th></th></tr></thead><tbody>
      ${c.edges.map(([a, b], i) => `<tr><td>${esc(nameOf(a))} <span class="muted small">${esc(a)}</span></td><td>→</td><td>${esc(nameOf(b))} <span class="muted small">${esc(b)}</span></td><td><button class="danger" data-cx-del="${i}">Remove</button></td></tr>`).join("") || `<tr><td colspan="4" class="muted">No connections yet.</td></tr>`}
    </tbody></table></div>`;
  $("#cx-from") && ($("#cx-from").onchange = () => screens.connections());
  $("#cx-add").onclick = () => { const to = $("#cx-to").value; if (!to) return; c.edges.push([fromEq.id, to]); markDirty(); screens.connections(); };
  document.querySelectorAll("[data-cx-del]").forEach((b) => { b.onclick = () => { c.edges.splice(+b.dataset.cxDel, 1); markDirty(); screens.connections(); }; });
};

// ---------- truck processes and movement (slice 9b) ----------
// A truck path interleaves waiting areas and steps. The builder shows one "slot" before each step:
//   open   unlimited waiting (the engine's default when an activity has no path at all)
//   none   no waiting space: the truck goes straight on and blocks its station if the next one is busy
//   area:X a configured waiting area
// When every slot is "open" the activity has no explicit path. Otherwise "open" slots become automatic unlimited
// areas (ids open_<activity>_<n>), kept only while a path uses them.
const stepLabel = (s) => (S.meta.truck_steps.find((x) => x.id === s) || { label: s }).label;
const actLabel = (a) => (S.meta.activities.find((x) => x.id === a) || { label: a }).label;
const isAuto = (id) => /^open_/.test(id);

function getSlots(act) {
  const c = S.config, seq = c.sequences[act] || [], path = (c.truck_paths || {})[act];
  if (!path) return seq.map(() => "open");
  const out = []; let pending = null, i = 0;
  for (const el of path) {
    if (i < seq.length && el === seq[i]) { out.push(pending === null ? "none" : isAuto(pending) ? "open" : "area:" + pending); pending = null; i++; }
    else pending = el;
  }
  while (out.length < seq.length) out.push("open");
  return out;
}

function setSlots(act, slots) {
  const c = S.config, seq = c.sequences[act] || [];
  c.truck_paths = c.truck_paths || {};
  c.truck_areas = c.truck_areas || [];
  if (seq.every((step, i) => step === "grade" || (slots[i] || "open") === "open")) delete c.truck_paths[act];
  else {
    const path = [];
    seq.forEach((step, i) => {
      const s = step === "grade" ? "none" : slots[i] || "open";  // grading: the truck waits where it is
      if (s === "open") {
        const id = `open_${act}_${i + 1}`;
        if (!c.truck_areas.some((a) => a.id === id)) c.truck_areas.push({ id, name: `Open waiting before ${stepLabel(step)}`, capacity: null });
        path.push(id);
      } else if (s.startsWith("area:")) path.push(s.slice(5));
      path.push(step);
    });
    c.truck_paths[act] = path;
  }
  const used = new Set(Object.values(c.truck_paths).flat().filter(Boolean));
  c.truck_areas = c.truck_areas.filter((a) => !isAuto(a.id) || used.has(a.id));
  c.truck_bypasses = (c.truck_bypasses || []).filter((b) => (c.truck_paths[b.activity] || []).includes(b.from));
}

function setSequence(act, seq) {
  const c = S.config, old = c.sequences[act] || [], oldSlots = getSlots(act);
  const slotOf = Object.fromEntries(old.map((s, i) => [s, oldSlots[i]]));
  c.sequences[act] = seq;
  c.release_rules = (c.release_rules || []).filter((r) => r.activity !== act || seq.includes(r.step));
  setSlots(act, seq.map((s) => slotOf[s] || "open"));
}

function stationsFor(step, act) {
  const info = S.meta.truck_steps.find((x) => x.id === step);
  if (!info) return [];
  return S.config.equipment.filter((e) => e.type === info.station && (!e.activities || e.activities.includes(act))
    && !(step === "weigh_in" && e.moves === "out") && !(step === "weigh_out" && e.moves === "in"));
}

screens.processes = () => {
  if (needSite()) return;
  const c = S.config;
  c.release_rules = c.release_rules || [];
  const cards = S.meta.activities.map(({ id: act, label }) => {
    const seq = c.sequences[act] || [];
    const unused = S.meta.activity_steps[act].filter((s) => !seq.includes(s));
    const rows = seq.map((step, i) => {
      const st = stationsFor(step, act);
      const rule = c.release_rules.find((r) => r.activity === act && r.step === step);
      const conds = S.meta.place_steps.includes(step) ? S.meta.release_conditions.map((cd) =>
        `<label style="display:inline-flex;gap:4px;margin:0;color:var(--text)"><input type="checkbox" data-rule="${act}|${step}|${cd.id}" ${rule && rule.when.includes(cd.id) ? "checked" : ""}> only when ${esc(cd.label)}</label>`).join("") : `<span class="muted small">–</span>`;
      return `<tr><td>${i + 1}</td><td><strong>${esc(stepLabel(step))}</strong><div class="muted small">${st.length ? "at " + st.map((e) => esc(e.name || e.id)).join(", ") : step === "grade" ? "graded off the truck" : `<span class="req">no equipment serves this step yet</span>`}</div></td>
        <td>${conds}</td>
        <td style="white-space:nowrap"><button data-mv="${act}|${i}|-1" ${i ? "" : "disabled"} aria-label="Move up">↑</button> <button data-mv="${act}|${i}|1" ${i < seq.length - 1 ? "" : "disabled"} aria-label="Move down">↓</button> <button class="danger" data-rm="${act}|${i}">Remove</button></td></tr>`;
    }).join("");
    return `<div class="card"><h2>${esc(label)} trucks</h2>
      <table><thead><tr><th>#</th><th>Step</th><th>The truck leaves this place after the service, and…</th><th></th></tr></thead><tbody>${rows || `<tr><td colspan="4" class="muted">No steps: no ${esc(label.toLowerCase())} trucks will be simulated.</td></tr>`}</tbody></table>
      <div class="actions">${unused.length ? `<select id="add-${act}">${unused.map((s) => `<option value="${s}">${esc(stepLabel(s))}</option>`).join("")}</select><button data-addstep="${act}">Add step</button>` : ""}</div></div>`;
  }).join("");
  $("#main").innerHTML = `<h1>Truck processes</h1><p class="lead">The steps each kind of truck goes through, in order. A sample is graded off the truck while it moves on; tick "only when its sample has been graded" on a step where the truck must wait for the result (for example on the incoming weighbridge).</p>${cards}`;
  document.querySelectorAll("[data-addstep]").forEach((b) => { b.onclick = () => { const act = b.dataset.addstep; setSequence(act, [...(c.sequences[act] || []), $(`#add-${act}`).value]); markDirty(); render(); }; });
  document.querySelectorAll("[data-rm]").forEach((b) => { b.onclick = () => { const [act, i] = b.dataset.rm.split("|"); const seq = [...c.sequences[act]]; seq.splice(+i, 1); setSequence(act, seq); markDirty(); render(); }; });
  document.querySelectorAll("[data-mv]").forEach((b) => { b.onclick = () => {
    const [act, i, d] = b.dataset.mv.split("|"); const seq = [...c.sequences[act]], j = +i + +d;
    [seq[+i], seq[j]] = [seq[j], seq[+i]]; setSequence(act, seq); markDirty(); render();
  }; });
  document.querySelectorAll("[data-rule]").forEach((el) => { el.onchange = () => {
    const [act, step, cond] = el.dataset.rule.split("|");
    let rule = c.release_rules.find((r) => r.activity === act && r.step === step);
    if (!rule) { rule = { activity: act, step, when: ["service_done"] }; c.release_rules.push(rule); }
    rule.when = el.checked ? [...new Set([...rule.when, cond])] : rule.when.filter((x) => x !== cond);
    if (!rule.when.some((x) => x !== "service_done")) c.release_rules = c.release_rules.filter((r) => r !== rule);
    markDirty();
  }; });
};

screens.movement = () => {
  if (needSite()) return;
  const c = S.config;
  c.truck_areas = c.truck_areas || [];
  const areas = c.truck_areas.filter((a) => !isAuto(a.id));
  const areaRows = areas.map((a) => {
    const i = c.truck_areas.indexOf(a);
    return `<tr><td><input data-ar="${i}|id" value="${esc(a.id)}" size="10"></td><td><input data-ar="${i}|name" value="${esc(a.name)}"></td>
      <td><input type="number" min="1" data-ar="${i}|capacity" value="${esc(a.capacity ?? "")}" placeholder="unlimited" style="width:100px"> <span class="unit">trucks</span></td>
      <td><input type="checkbox" data-ar="${i}|single_file" ${a.single_file ? "checked" : ""} aria-label="single file"></td><td><button class="danger" data-ardel="${i}">Remove</button></td></tr>`;
  }).join("");
  const pathCards = S.meta.activities.map(({ id: act, label }) => {
    const seq = c.sequences[act] || [];
    if (!seq.length) return "";
    const slots = getSlots(act);
    const opts = (cur) => `<option value="open" ${cur === "open" ? "selected" : ""}>Unlimited waiting</option><option value="none" ${cur === "none" ? "selected" : ""}>No waiting space (goes straight on, blocks if busy)</option>` +
      areas.map((a) => `<option value="area:${esc(a.id)}" ${cur === "area:" + a.id ? "selected" : ""}>${esc(a.name)} (${a.capacity ?? "unlimited"})</option>`).join("");
    const rows = seq.map((step, i) => `<tr><td class="muted small">before</td><td>${step === "grade"
      ? `<span class="muted small">none: the truck waits for its result where it is (set "only when graded" on the step before, in Truck processes, to hold that place)</span>`
      : `<select data-slot="${act}|${i}" aria-label="Waiting before ${esc(stepLabel(step))}">${opts(slots[i])}</select>`}</td><td>→ <strong>${esc(stepLabel(step))}</strong></td></tr>`).join("");
    return `<div class="card"><h2>${esc(label)} trucks</h2><p class="muted small">${(c.truck_paths || {})[act] ? "Explicit path: " + esc(c.truck_paths[act].join(" → ")) : "No explicit path: unlimited waiting before every step (default)."}</p><table><tbody>${rows}</tbody></table></div>`;
  }).join("");
  const bypasses = c.truck_bypasses || [];
  const bpRows = bypasses.map((b, i) => `<tr><td>${esc(actLabel(b.activity))}</td><td>${esc(b.from)}</td><td>${esc(b.to)}</td><td><button class="danger" data-bpdel="${i}">Remove</button></td></tr>`).join("");
  const bpAct = $("#bp-act") ? $("#bp-act").value : "unload";
  const bpPath = (c.truck_paths || {})[bpAct] || [];
  $("#main").innerHTML = `<h1>Truck movement</h1><p class="lead">Where trucks wait between steps and how many fit. A truck holds one place at a time; if the next place is full it stays where it is, blocking that station.</p>
    <div class="card"><h2>Waiting areas</h2><table><thead><tr><th>Id</th><th>Name</th><th>Capacity</th><th>Single file</th><th></th></tr></thead><tbody>${areaRows || `<tr><td colspan="5" class="muted">No waiting areas defined.</td></tr>`}</tbody></table>
      <div class="actions"><button id="ar-add">Add waiting area</button></div><p class="muted small">Single file: only the front truck may move on (a physical lane, not a queue rule).</p></div>
    ${pathCards}
    <div class="grid2"><div class="card"><h2>Bypasses</h2><p class="muted small">A declared lane that lets a truck needing no sampling leave a waiting area directly to a later point.</p>
      <table><thead><tr><th>Trucks</th><th>From</th><th>To</th><th></th></tr></thead><tbody>${bpRows || `<tr><td colspan="4" class="muted">None.</td></tr>`}</tbody></table>
      <div class="tri"><select id="bp-act">${S.meta.activities.map((a) => `<option value="${a.id}" ${a.id === bpAct ? "selected" : ""}>${esc(a.label)}</option>`).join("")}</select>
      <select id="bp-from">${bpPath.filter((x) => c.truck_areas.some((a) => a.id === x)).map((x) => `<option>${esc(x)}</option>`).join("") || `<option value="">no area on this path</option>`}</select> →
      <select id="bp-to">${bpPath.map((x) => `<option>${esc(x)}</option>`).join("")}</select><button id="bp-add">Add</button></div></div>
      <div class="card"><h2>Gridlock prevention</h2><select id="dl" class="wide">${S.meta.deadlock_prevention.map((d) => `<option value="${d.id}" ${(c.deadlock_prevention || "reserve_next_space") === d.id ? "selected" : ""}>${esc(d.label)}</option>`).join("")}</select></div></div>`;
  $("#ar-add").onclick = () => { let n = 1; while (c.truck_areas.some((a) => a.id === `Q${n}`)) n++; c.truck_areas.push({ id: `Q${n}`, name: `Queue ${n}`, capacity: 2 }); markDirty(); render(); };
  document.querySelectorAll("[data-ar]").forEach((el) => { el.onchange = () => {
    const [i, k] = el.dataset.ar.split("|"), a = c.truck_areas[+i];
    if (k === "single_file") { if (el.checked) a.single_file = true; else delete a.single_file; }
    else if (k === "capacity") a.capacity = el.value === "" ? null : Math.max(1, Math.round(+el.value));
    else if (k === "id") {
      const nid = el.value.trim(), old = a.id;
      if (!nid || c.truck_areas.some((x) => x.id === nid)) { toast("That id is empty or already used."); return render(); }
      a.id = nid;
      Object.keys(c.truck_paths || {}).forEach((act) => { c.truck_paths[act] = (c.truck_paths[act] || []).map((x) => (x === old ? nid : x)); });
      (c.truck_bypasses || []).forEach((b) => { if (b.from === old) b.from = nid; if (b.to === old) b.to = nid; });
    } else a[k] = el.value;
    markDirty(); render();
  }; });
  document.querySelectorAll("[data-ardel]").forEach((b) => { b.onclick = () => {
    const a = c.truck_areas[+b.dataset.ardel];
    Object.keys(c.truck_paths || {}).forEach((act) => { const slots = getSlots(act).map((s) => (s === "area:" + a.id ? "open" : s)); setSlots(act, slots); });
    c.truck_areas = c.truck_areas.filter((x) => x !== a); markDirty(); render();
  }; });
  document.querySelectorAll("[data-slot]").forEach((el) => { el.onchange = () => {
    const [act, i] = el.dataset.slot.split("|"), slots = getSlots(act); slots[+i] = el.value; setSlots(act, slots); markDirty(); render();
  }; });
  $("#bp-act").onchange = () => screens.movement();
  $("#bp-add").onclick = () => {
    const from = $("#bp-from").value, to = $("#bp-to").value;
    if (!from || !to || bpPath.indexOf(to) <= bpPath.indexOf(from)) return toast("Choose a waiting area and a later point on the path.");
    c.truck_bypasses = [...bypasses, { activity: bpAct, from, to, for: "not_sampled" }]; markDirty(); render();
  };
  document.querySelectorAll("[data-bpdel]").forEach((b) => { b.onclick = () => { c.truck_bypasses.splice(+b.dataset.bpdel, 1); markDirty(); render(); }; });
  $("#dl").onchange = (ev) => { c.deadlock_prevention = ev.target.value; markDirty(); };
};

screens.check = () => {
  if (needSite()) return;
  const r = S.report;
  if (!r) { $("#main").innerHTML = `<h1>Check</h1><p class="lead">Checking…</p>`; return; }
  const group = (sev, title) => {
    const fs = r.findings.filter((f) => f.severity === sev);
    if (!fs.length) return "";
    return `<h2>${title} (${fs.length})</h2>` + fs.map((f) => `<div class="finding ${sev}"><span class="sev">${sev}</span> ${esc(f.message)}
      ${f.fix ? `<div class="fix">How to fix: ${esc(f.fix)}</div>` : ""}
      <div>${f.location.filter((id) => eqById(id)).map((id) => `<span class="chip" data-goto="${esc(id)}">${esc(id)}</span>`).join("")}${(f.systems || []).map((s) => `<span class="muted small">system ${esc(s)} </span>`).join("")}</div></div>`).join("");
  };
  $("#main").innerHTML = `<h1>Check</h1><p class="lead">The engine checks the whole configuration before any run. Errors must be fixed before a run; warnings need your attention; notes explain.</p>
    <div class="banner ${r.ok ? (r.warnings ? "warn" : "good") : "error"}">${r.ok ? (r.warnings ? `Can run, with ${r.warnings} warning(s) to review.` : "No problems found: this configuration can run.") : `${r.errors} error(s) must be fixed before a run.`}</div>
    <div class="card">${group("error", "Errors")}${group("warning", "Warnings")}${group("note", "Notes")}${r.findings.length ? "" : `<p class="muted">Nothing to report.</p>`}</div>`;
  document.querySelectorAll("[data-goto]").forEach((ch) => { ch.onclick = () => { S.selected = ch.dataset.goto; location.hash = "#equipment"; }; });
};

screens.versions = async () => {
  if (needSite()) return;
  const c = S.config;
  let history = [];
  try { history = await api("GET", `/sites/${encodeURIComponent(c.id)}/history`); } catch (e) { if (e.status !== 404) throw e; }
  $("#main").innerHTML = `<h1>Save &amp; versions</h1><p class="lead">Each save creates a new, numbered version. Saved versions are never changed, so every run can be traced to exactly what was simulated.</p>
    <div class="grid2"><div class="card"><h2>Save a new version</h2>
      <label for="v-note">What changed?</label><input id="v-note" class="wide" placeholder="e.g. added hopper H3 to Silo B">
      <p class="muted small">Configurations that cannot run yet are saved as drafts, with their check result recorded.</p>
      <div class="actions"><button class="primary" id="v-save">Save version</button></div></div>
      <div class="card"><h2>Compare two versions</h2>
      ${history.length > 1 ? `<div class="tri"><select id="v-a">${history.map((h) => `<option ${h.version === history.length - 1 ? "selected" : ""}>${h.version}</option>`).join("")}</select> → <select id="v-b">${history.map((h) => `<option ${h.version === history.length ? "selected" : ""}>${h.version}</option>`).join("")}</select><button id="v-diff">Compare</button></div><div id="v-diffout"></div>` : `<p class="muted">Save at least two versions to compare them.</p>`}</div></div>
    <div class="card"><h2>History of ${esc(c.id)}</h2><table><thead><tr><th>Version</th><th>Note</th><th>Saved</th><th>Check</th><th>Configuration hash</th><th></th></tr></thead><tbody>
      ${history.slice().reverse().map((h) => `<tr><td>v${h.version}</td><td>${esc(h.note)}</td><td class="small">${esc(h.created)}</td><td>${h.report.ok ? `<span class="badge good">can run</span>` : `<span class="badge error">${h.report.errors} error(s)</span>`}</td><td class="small muted">${esc(h.config_hash.slice(0, 12))}…</td><td><button data-load="${h.version}">Open</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">Not saved yet.</td></tr>`}
    </tbody></table></div>`;
  $("#v-save").onclick = async () => {
    try {
      const v = await api("POST", "/sites", { config: c, note: $("#v-note").value });
      S.saved = { site_id: v.site_id, version: v.version, config_hash: v.config_hash }; S.config.version = v.version; S.dirty = false; S.example = null;
      header(); toast(`Saved ${v.site_id} version ${v.version}` + (v.report.ok ? "." : " as a draft (it has errors)."));
      screens.versions();
    } catch (e) { toast("Not saved: " + e.message); }
  };
  document.querySelectorAll("[data-load]").forEach((b) => { b.onclick = async () => {
    if (!guard()) return;
    const n = +b.dataset.load, cfg = await api("GET", `/sites/${encodeURIComponent(c.id)}?version=${n}`);
    const h = history.find((x) => x.version === n);
    open(cfg, { site_id: c.id, version: n, config_hash: h.config_hash });
  }; });
  if ($("#v-diff")) $("#v-diff").onclick = async () => {
    const d = await api("GET", `/sites/${encodeURIComponent(c.id)}/diff?a=${$("#v-a").value}&b=${$("#v-b").value}`);
    $("#v-diffout").innerHTML = d.length ? `<table><thead><tr><th>Change</th><th>Where</th><th>Field</th><th>From</th><th>To</th></tr></thead><tbody>${d.map((x) => `<tr><td>${esc(x.kind)}</td><td>${esc(x.where)}</td><td>${esc(x.field ?? "")}</td><td>${esc(JSON.stringify(x.from ?? ""))}</td><td>${esc(JSON.stringify(x.to ?? ""))}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">The two versions are identical.</p>`;
  };
};

const KPIS = [
  ["unload.completed", "Receiving trucks completed", "trucks"],
  ["unload.mean_turnaround_min", "Mean turnaround (completed trucks only)", "min"],
  ["unload.p90_turnaround_min", "90th percentile turnaround (completed only)", "min"],
  ["unload.unfinished", "Receiving trucks unfinished at the end", "trucks"],
  ["received_t", "Grain received", "t"],
  ["unload.starved", "Trucks waiting beyond the starvation threshold", "trucks"],
];

screens.run = () => {
  if (needSite()) return;
  const ready = S.saved && !S.dirty;
  const r = S.report;
  $("#main").innerHTML = `<h1>Run</h1><p class="lead">A run simulates a <strong>saved</strong> version, so its results can always be traced to exactly what was simulated. Each replication is a simulated day with its own random arrivals; repeating with the same seed gives the same results.</p>
    ${!ready ? `<div class="banner warn">${S.saved ? "You have unsaved changes: save a new version first." : "Save this configuration first."} <a href="#versions">Save &amp; versions</a></div>` : ""}
    ${r && !r.ok ? `<div class="banner error">The configuration has ${r.errors} error(s). <a href="#check">See the check</a>.</div>` : ""}
    <div class="card"><h2>Run version ${S.saved ? S.saved.version : "–"}</h2>
      <div class="tri"><label for="r-reps" style="margin:0">Replications</label><input id="r-reps" type="number" min="1" max="500" value="10">
      <label for="r-seed" style="margin:0">Seed</label><input id="r-seed" type="number" value="20261019">
      <label for="r-days" style="margin:0">Days</label><input id="r-days" type="number" min="1" max="60" value="1">
      <label for="r-dem" style="margin:0">Demand ×</label><input id="r-dem" type="number" step="0.1" min="0.1" value="1"></div>
      <div class="actions"><button class="primary" id="r-start" ${ready && (!r || r.ok) ? "" : "disabled"}>Run simulation</button></div></div>
    <div id="r-list">${S.runs.map(runCard).join("")}</div>`;
  $("#r-start").onclick = async () => {
    try {
      const body = { site_id: S.saved.site_id, version: S.saved.version, replications: +$("#r-reps").value, base_seed: +$("#r-seed").value, days: +$("#r-days").value, demand_factor: +$("#r-dem").value };
      const st = await api("POST", "/runs", body);
      S.runs.unshift({ id: st.run_id, state: st.state, body, results: null, record: null });
      screens.run(); poll(st.run_id);
    } catch (e) { toast("Not started: " + e.message); }
  };
};

function fmt(v, unit) { return v === null || v === undefined ? "–" : (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) + (unit ? ` ${unit}` : ""); }

function runCard(run) {
  const head = `<h2>Run ${esc(run.id)} · version ${run.body.version} · ${run.body.replications} replication(s), seed ${run.body.base_seed}${run.body.demand_factor !== 1 ? `, demand ×${run.body.demand_factor}` : ""} <span class="label-sim">SIMULATED</span></h2>`;
  if (run.state === "failed") return `<div class="card">${head}<div class="banner error">Failed: ${esc(run.record && run.record.error)}</div></div>`;
  if (!run.results) return `<div class="card">${head}<p class="muted">State: ${esc(run.state)}…</p></div>`;
  const s = run.results.summary, m = run.results.metadata;
  const kpis = KPIS.filter(([k]) => s[k]).map(([k, name, unit]) => {
    const i = s[k]; return `<div class="kpi"><div class="name">${esc(name)}</div><div class="val">${fmt(i.mean, unit)}</div><div class="ci">${i.half_width !== null ? `95% interval ${fmt(i.low)} – ${fmt(i.high)}` : "single replication: no interval"} · n=${i.n}</div></div>`;
  }).join("");
  return `<div class="card">${head}
    ${run.results.failed ? `<div class="banner warn">${run.results.failed} replication(s) failed and are not in these figures (${esc(m.summary_scope)}).</div>` : ""}
    <div class="kpis">${kpis}</div>
    <p class="muted small">Engine ${esc(m.engine_version)} · configuration ${esc(m.config_hash.slice(0, 12))}… · seeds ${esc(m.seeds.join(", "))}. These are simulation outputs for the configuration as entered; they are not validated against observations of a real silo.</p>
    <details><summary class="small">Assumptions (${m.assumptions.length})</summary><ul class="small">${m.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details></div>`;
}

async function poll(id) {
  const run = S.runs.find((r) => r.id === id);
  for (;;) {
    const rec = await api("GET", `/runs/${id}`);
    run.state = rec.state; run.record = rec;
    if (rec.state === "done") { run.results = await api("GET", `/runs/${id}/results`); break; }
    if (rec.state === "failed") break;
    if (current() === "run") $("#r-list").innerHTML = S.runs.map(runCard).join("");
    await new Promise((res) => setTimeout(res, 700));
  }
  if (current() === "run") $("#r-list").innerHTML = S.runs.map(runCard).join("");
  toast(run.state === "done" ? `Run ${id} finished.` : `Run ${id} failed.`);
}

screens.advanced = () => {
  if (needSite()) return;
  $("#main").innerHTML = `<h1>Advanced</h1><p class="lead">The whole configuration as the engine reads it. Labour, operating rules and demand get their own screens in the next slice; until then they are kept exactly as loaded.</p>
    <div class="card"><pre class="json">${esc(JSON.stringify(S.config, null, 1))}</pre></div>`;
};

// ---------- routing ----------
function focusKey(el) {  // a selector that finds the same input after a redraw
  if (!el || el === document.body) return null;
  if (el.id) return "#" + el.id;
  for (const k of ["field", "multi", "sysId", "sysName", "comId", "comName", "slot", "ar", "rule"]) {
    if (el.dataset[k] !== undefined) return `[data-${k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())}="${el.dataset[k]}"]` + (el.value && k === "multi" ? `[value="${el.value}"]` : "");
  }
  if (el.dataset.tri !== undefined) return `[data-tri="${el.dataset.tri}"][data-i="${el.dataset.i}"]`;
  return null;
}

async function render() {
  const name = current();
  const key = focusKey(document.activeElement);
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
  try { await (screens[name] || screens.silo)(); }
  catch (e) { $("#main").innerHTML = `<div class="banner error">Something went wrong: ${esc(e.message)}</div>`; }
  const again = key && document.querySelector(key);
  if (again) again.focus();
}

window.addEventListener("hashchange", render);
window.addEventListener("beforeunload", (ev) => { if (S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });

(async () => {
  try { S.meta = await api("GET", "/meta"); }
  catch (e) { $("#main").innerHTML = `<div class="banner error">The engine API is not reachable: ${esc(e.message)}</div>`; return; }
  header(); render();
})();
