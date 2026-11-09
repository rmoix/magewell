/* Magewell Mini-NMS — client del dashboard (sense dependències). */
"use strict";

const S = {
  devices: new Map(),
  summary: {},
  alerts: [],
  scan: null,
  interval: 3,
  cycleMs: null,
  lastEvent: 0,
  f: { status: "ALL", role: "ALL", location: "ALL", q: "", problems: false, sort: "location", view: "grid", sound: false },
  openDevice: null,
  drawerMode: null,
  page: "monitor",
  routing: { sources: [], last_refresh: null, enabled: true },
  unlocked: false, // mai es desa: sempre arrenca bloquejat
  pending: new Map(), // rx id -> nom de la font que s'està enrutant
  routeErr: null, // { rx, tx, until }
  r: { q: "", showOffline: true },
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const STATUS_LABEL = { OK: "OK", WARNING: "AVÍS", NO_SIGNAL: "SENSE SENYAL", OFFLINE: "OFFLINE", AUTH_ERROR: "AUTH", UNKNOWN: "…" };
const SEVERITY_ORDER = { NO_SIGNAL: 0, OFFLINE: 1, AUTH_ERROR: 2, WARNING: 3, UNKNOWN: 4, OK: 5 };

/* ------------------------------------------------------------------ preferències */
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem("nms-prefs") || "{}");
    for (const k of ["role", "location", "problems", "sort", "view", "sound"]) if (k in p) S.f[k] = p[k];
    if (p.page === "routing" || p.page === "monitor") S.page = p.page;
    if (location.hash === "#enrutament") S.page = "routing";
  } catch (_) { /* sense emmagatzematge: valors per defecte */ }
}
function savePrefs() {
  try {
    const { role, location, problems, sort, view, sound } = S.f;
    localStorage.setItem("nms-prefs", JSON.stringify({ role, location, problems, sort, view, sound, page: S.page }));
  } catch (_) {}
}

/* ------------------------------------------------------------------ SSE */
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => setLive(true);
  es.onerror = () => setLive(false);
  es.onmessage = (e) => {
    S.lastEvent = Date.now();
    let msg;
    try { msg = JSON.parse(e.data); } catch (_) { return; }
    handle(msg.type, msg.data);
  };
}

function handle(type, d) {
  switch (type) {
    case "snapshot":
      S.alerts = d.alerts || [];
      S.scan = d.scan;
      S.interval = d.polling_interval || 3;
      if (d.routing) S.routing = d.routing;
      // fallthrough
    case "cycle":
    case "devices": {
      const prev = S.devices;
      S.devices = new Map((d.devices || []).map((x) => [x.id, x]));
      S.changed = new Set();
      for (const [id, dev] of S.devices) {
        const p = prev.get(id);
        if (p && p.status !== dev.status) S.changed.add(id);
      }
      S.summary = d.summary || S.summary;
      if (d.cycle_ms != null) S.cycleMs = d.cycle_ms;
      render();
      if (S.drawerMode === "device" && S.openDevice) renderDeviceDrawer(S.openDevice, false);
      break;
    }
    case "alert":
      S.alerts.unshift(d);
      S.alerts.length = Math.min(S.alerts.length, 300);
      renderAlertsBadge();
      if (S.drawerMode === "alerts") renderAlertsDrawer();
      if (d.severity === "error") beep();
      break;
    case "alerts_cleared":
      S.alerts = [];
      renderAlertsBadge();
      if (S.drawerMode === "alerts") renderAlertsDrawer();
      break;
    case "scan":
      S.scan = d;
      renderScan();
      if (S.drawerMode === "scan") renderScanDrawer();
      break;
    case "sources":
      S.routing = d;
      if (S.page === "routing") renderMatrix();
      break;
  }
}

function setLive(on) {
  $("#live-dot").className = "live-dot " + (on ? "on" : "err");
}

/* ------------------------------------------------------------------ render principal */
function render() {
  renderCounters();
  renderLocations();
  if (S.page === "routing") renderMatrix(); else renderDevices();
  renderAlertsBadge();
  renderScan();
  const s = S.summary;
  const problems = (s.no_signal || 0) + (s.offline || 0) + (s.auth_error || 0) + (s.warning || 0);
  document.title = problems ? `(${problems}) Magewell NMS` : "Magewell NMS";
  const t = s.last_poll ? new Date(s.last_poll).toLocaleTimeString() : "—";
  $("#subtitle").textContent = `${s.total || 0} equips · ${s.encoders || 0} encoders · ${s.decoders || 0} decoders · últim sondeig ${t}`;
  $("#foot-cycle").textContent = S.cycleMs != null ? `Cicle de sondeig: ${S.cycleMs} ms · interval ${S.interval} s` : "";
}

function renderCounters() {
  const s = S.summary;
  const map = { total: s.total, ok: s.ok, warning: s.warning, no_signal: s.no_signal, offline: s.offline, auth_error: s.auth_error };
  for (const [k, v] of Object.entries(map)) {
    const el = $(`#c-${k}`);
    if (el) {
      el.textContent = v ?? 0;
      el.parentElement.classList.toggle("zero", !v && k !== "total");
    }
  }
  $$(".counter").forEach((b) => b.classList.toggle("active", b.dataset.status === S.f.status && S.f.status !== "ALL"));
}

function renderLocations() {
  const sel = $("#f-location");
  const locs = [...new Set([...S.devices.values()].map((d) => d.location).filter(Boolean))].sort();
  const want = ["ALL", ...locs].join("|");
  if (sel.dataset.opts === want) return;
  sel.dataset.opts = want;
  sel.innerHTML = `<option value="ALL">Totes les ubicacions</option>` + locs.map((l) => `<option>${esc(l)}</option>`).join("");
  sel.value = locs.includes(S.f.location) ? S.f.location : "ALL";
  sel.classList.toggle("hidden", locs.length === 0);
}

function ipKey(ip) { return ip.split(".").map((n) => n.padStart(3, "0")).join("."); }

function filtered() {
  const f = S.f;
  const q = f.q.toLowerCase();
  let list = [...S.devices.values()].filter((d) => {
    if (f.status !== "ALL" && d.status !== f.status) return false;
    if (f.role !== "ALL" && d.role !== f.role) return false;
    if (f.location !== "ALL" && d.location !== f.location) return false;
    if (f.problems && d.status === "OK") return false;
    if (q) {
      const hay = [d.name, d.ip, d.model, d.serial, d.location, d.ndi?.name, d.signal?.label].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const byIp = (a, b) => ipKey(a.ip).localeCompare(ipKey(b.ip)) || a.port - b.port;
  const sorters = {
    ip: byIp,
    name: (a, b) => a.name.localeCompare(b.name, "ca") || byIp(a, b),
    status: (a, b) => SEVERITY_ORDER[a.status] - SEVERITY_ORDER[b.status] || a.name.localeCompare(b.name, "ca"),
    location: (a, b) => (!a.location - !b.location) || (a.location || "").localeCompare(b.location || "", "ca") ||
      (a.role || "").localeCompare(b.role || "") || a.name.localeCompare(b.name, "ca") || byIp(a, b),
  };
  return list.sort(sorters[f.sort] || byIp);
}

function renderDevices() {
  const box = $("#devices");
  const list = filtered();
  const empty = $("#empty");
  if (!S.devices.size) {
    box.innerHTML = "";
    empty.classList.remove("hidden");
    const scanning = S.scan && S.scan.running;
    empty.innerHTML = `<h2>${scanning ? "Escanejant la xarxa…" : "Encara no hi ha cap equip"}</h2>
      <p>${scanning ? "Buscant equips Magewell a les xarxes d'aquest PC." :
        "Prem <b>Escanejar xarxa</b> o afegeix equips a <code>config.yaml</code> (secció <code>devices</code>)."}</p>`;
    return;
  }
  if (!list.length) {
    box.innerHTML = "";
    empty.classList.remove("hidden");
    empty.innerHTML = `<h2>Cap equip amb aquests filtres</h2><p><button class="link" id="clear-filters">Treure filtres</button></p>`;
    $("#clear-filters").onclick = () => { Object.assign(S.f, { status: "ALL", role: "ALL", location: "ALL", q: "", problems: false }); syncControls(); render(); };
    return;
  }
  empty.classList.add("hidden");
  if (S.f.view === "list") {
    box.className = "list";
    box.innerHTML = `<div class="table-wrap"><table class="devtable"><thead><tr>
      <th>Estat</th><th>Nom</th><th>Rol</th><th>Senyal</th><th>NDI</th><th>IP</th><th>Temp</th><th>Problemes</th></tr></thead>
      <tbody>${list.map(rowHtml).join("")}</tbody></table></div>`;
  } else {
    box.className = "grid";
    box.innerHTML = list.map(cardHtml).join("");
  }
  S.changed = new Set();
}

function fmtUptime(s) {
  if (s == null) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
function tempClass(t) { return t == null ? "" : t >= 80 ? "hot" : t >= 70 ? "warm" : ""; }
function webUrl(d) { return `http://${d.ip}${d.port && d.port !== 80 ? ":" + d.port : ""}/`; }

function signalHtml(d) {
  const sig = d.signal || {};
  if (!d.is_online && d.status === "OFFLINE") return `<span class="fmt off">SENSE CONNEXIÓ</span>`;
  if (d.status === "AUTH_ERROR" || d.status === "UNKNOWN") return `<span class="fmt off">—</span>`;
  if (!sig.locked) return `<span class="fmt none">${d.role === "Decoder" ? "SENSE FONT NDI" : "SENSE SENYAL"}</span>`;
  const extra = [sig.sampling, sig.color_format, sig.color_depth ? sig.color_depth + "bit" : null].filter(Boolean).join(" · ");
  return `<span class="fmt">${esc(sig.label || `${sig.width}x${sig.height}`)}</span><span class="extra">${esc(extra)}</span>`;
}

function ndiHtml(d) {
  const n = d.ndi || {};
  const tally = (n.tally_program ? `<span class="tally pgm">PGM</span>` : "") + (n.tally_preview ? `<span class="tally pvw">PVW</span>` : "");
  if (d.role === "Decoder") {
    return `<div class="ndi"><span class="arrow">Font ◂</span> ${esc(n.name || "—")}${tally}</div>`;
  }
  if (d.role === "Encoder") {
    const parts = [];
    if (n.num_clients != null) parts.push(`${n.num_clients} receptor${n.num_clients === 1 ? "" : "s"}`);
    if (n.video_bitrate_kbps) parts.push(`${(n.video_bitrate_kbps / 1000).toFixed(0)} Mb/s`);
    return `<div class="ndi"><span class="arrow">NDI ▸</span> ${esc(n.name || "—")}${parts.length ? ` <span class="muted">· ${parts.join(" · ")}</span>` : ""}${tally}</div>`;
  }
  return `<div class="ndi muted">${esc(d.model || "Model desconegut")}</div>`;
}

function cardHtml(d) {
  const issues = (d.issues || []).filter(Boolean);
  const roleTag = d.role === "Encoder" ? "ENC" : d.role === "Decoder" ? "DEC" : "?";
  const sub = [d.location, d.model].filter(Boolean).join(" · ");
  return `<article class="card st-${d.status}${S.changed?.has(d.id) ? " flash" : ""}" data-id="${esc(d.id)}">
    <div class="card-head">
      <span class="role ${esc(d.role)}">${roleTag}</span>
      <div class="card-title"><h3 title="${esc(d.name)}">${esc(d.name)}</h3><div class="card-sub">${esc(sub || d.ip)}</div></div>
      <span class="chip">${STATUS_LABEL[d.status] || d.status}</span>
    </div>
    <div class="signal">${signalHtml(d)}</div>
    ${ndiHtml(d)}
    ${issues.length && d.status !== "OK" ? `<ul class="issues">${issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
    <div class="metrics">
      <div class="ip"><span>IP</span><b><a href="${webUrl(d)}" target="_blank" rel="noopener" data-stop>${esc(d.ip)}${d.port !== 80 ? ":" + d.port : ""}</a></b></div>
      <div><span>Temp</span><b class="${tempClass(d.temperature_c)}">${d.temperature_c != null ? d.temperature_c.toFixed(0) + "°C" : "—"}</b></div>
      <div><span>CPU</span><b>${d.cpu_usage != null ? d.cpu_usage.toFixed(0) + "%" : "—"}</b></div>
      <div><span>Resp.</span><b>${d.response_time_ms != null ? Math.round(d.response_time_ms) + " ms" : "—"}</b></div>
    </div>
  </article>`;
}

function rowHtml(d) {
  const sig = d.signal || {};
  const sigText = d.status === "OFFLINE" ? "—" : sig.locked ? sig.label : d.role === "Decoder" ? "SENSE FONT" : "SENSE SENYAL";
  return `<tr class="st-${d.status}" data-id="${esc(d.id)}">
    <td class="stcell"><span class="chip">${STATUS_LABEL[d.status]}</span></td>
    <td><b>${esc(d.name)}</b><div class="muted small">${esc([d.location, d.model].filter(Boolean).join(" · "))}</div></td>
    <td>${esc(d.role === "Unknown" ? "?" : d.role)}</td>
    <td class="mono">${esc(sigText)}</td>
    <td>${esc(d.ndi?.name || "—")}${d.role === "Encoder" && d.ndi?.num_clients != null ? ` <span class="muted">(${d.ndi.num_clients})</span>` : ""}</td>
    <td class="mono"><a href="${webUrl(d)}" target="_blank" rel="noopener" data-stop class="link">${esc(d.ip)}${d.port !== 80 ? ":" + d.port : ""}</a></td>
    <td class="mono ${tempClass(d.temperature_c)}">${d.temperature_c != null ? d.temperature_c.toFixed(0) + "°" : "—"}</td>
    <td class="small">${d.status === "OK" ? "" : esc((d.issues || []).join(" · "))}</td>
  </tr>`;
}

/* ------------------------------------------------------------------ pàgines */
function setPage(page) {
  S.page = page;
  $$("[data-page]").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === page);
    b.setAttribute("aria-selected", b.dataset.page === page);
  });
  $("#page-monitor").classList.toggle("hidden", page !== "monitor");
  $("#main-monitor").classList.toggle("hidden", page !== "monitor");
  $("#page-routing").classList.toggle("hidden", page !== "routing");
  $("#main-routing").classList.toggle("hidden", page !== "routing");
  history.replaceState(null, "", page === "routing" ? "#enrutament" : location.pathname);
  savePrefs();
  render();
}

/* ------------------------------------------------------------------ matriu d'enrutament */
const sameSrc = (a, b) => !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();
let lockTimer;

function setUnlocked(on) {
  if (on && S.routing.enabled === false) { toast("L'enrutament està desactivat a config.yaml (routing.enabled)", true); return; }
  S.unlocked = on;
  const b = $("#btn-lock");
  b.classList.toggle("unlocked", on);
  b.setAttribute("aria-pressed", on);
  b.textContent = on ? "Edició activa · clica per bloquejar" : "Bloquejat · clica per editar";
  $("#r-banner").classList.toggle("hidden", !on);
  touchLock();
  renderMatrix();
}
function touchLock() {
  clearTimeout(lockTimer);
  if (S.unlocked) lockTimer = setTimeout(() => { setUnlocked(false); toast("Matriu bloquejada automàticament"); }, 120000);
}

function matrixData() {
  const q = S.r.q.toLowerCase();
  const decoders = [...S.devices.values()].filter((d) => d.role === "Decoder");
  let rows = decoders.filter((d) => !q || [d.name, d.ip, d.location, d.ndi?.name].join(" ").toLowerCase().includes(q));
  if (!rows.length) rows = decoders; // el filtre no coincideix amb cap receptor: es filtren només les fonts

  let cols = (S.routing.sources || []).map((s) => ({ ...s }));
  // Fonts que algun decoder té assignades però que ja no es veuen a la xarxa
  for (const d of decoders) {
    const cur = d.ndi?.name;
    if (cur && !cols.some((c) => sameSrc(c.name, cur))) {
      const m = cur.match(/^(.*?)\s*\((.*)\)\s*$/);
      cols.push({ name: cur, machine: m ? m[1] : cur, stream: m ? m[2] : "", online: false, missing: true });
    }
  }
  if (!S.r.showOffline) cols = cols.filter((c) => c.online || decoders.some((d) => sameSrc(d.ndi?.name, c.name)));
  const colsQ = cols.filter((c) => !q || c.name.toLowerCase().includes(q));
  if (colsQ.length) cols = colsQ;
  cols.sort((a, b) => a.machine.localeCompare(b.machine, "ca") || a.stream.localeCompare(b.stream, "ca"));
  rows.sort((a, b) => (!a.location - !b.location) || (a.location || "").localeCompare(b.location || "", "ca") || a.name.localeCompare(b.name, "ca"));
  return { rows, cols };
}

function cellState(d, c) {
  const pend = S.pending.get(d.id);
  const routed = sameSrc(d.ndi?.name, c.name);
  if (S.routeErr && S.routeErr.rx === d.id && sameSrc(S.routeErr.tx, c.name) && Date.now() < S.routeErr.until) return "err";
  if (pend) return sameSrc(pend, c.name) ? "pending" : routed ? "old" : "";
  if (!routed) return "";
  return d.is_online && d.signal?.locked ? "ok" : "bad";
}

function renderMatrix() {
  const table = $("#matrix");
  const empty = $("#r-empty");
  const { rows, cols } = matrixData();
  const lr = S.routing.last_refresh ? new Date(S.routing.last_refresh).toLocaleTimeString() : "—";
  $("#r-info").textContent = `${cols.length} fonts · ${rows.length} decoders · fonts actualitzades ${lr}`;

  if (!rows.length || !cols.length) {
    table.innerHTML = "";
    empty.classList.remove("hidden");
    empty.innerHTML = !rows.length
      ? `<h2>No hi ha cap decoder</h2><p>Els receptors (Rx) són els decoders Magewell (Pro Convert NDI to HDMI/SDI). Quan se'n detecti algun, apareixerà aquí.</p>`
      : `<h2>Encara no s'ha trobat cap font NDI</h2><p>La llista de fonts la proporcionen els decoders. Prem <b>Refrescar fonts</b>.</p>`;
    return;
  }
  empty.classList.add("hidden");
  table.className = "matrix " + (S.unlocked ? "unlocked" : "locked");

  // Agrupació per màquina (equivalent al "dispositiu" de Dante; el flux és el "canal")
  const groups = [];
  for (const c of cols) {
    const g = groups[groups.length - 1];
    if (g && g.machine === c.machine) g.n++; else groups.push({ machine: c.machine, n: 1 });
  }
  const encStatus = (c) => (c.device_id && S.devices.get(c.device_id)) ? S.devices.get(c.device_id).status : null;

  let h = `<thead><tr class="groups"><th class="corner" rowspan="2"><span class="axis tx">Tx · fonts NDI →</span><span class="axis">Rx · decoders ↓</span></th>`;
  // Una màquina amb una sola font: la columna ja mostra el nom complet, la capçalera de grup queda buida.
  h += groups.map((g) => `<th colspan="${g.n}" title="${esc(g.machine)}">${g.n > 1 ? esc(g.machine) : ""}</th>`).join("");
  h += `</tr><tr class="cols">`;
  const groupSize = Object.fromEntries(groups.map((g) => [g.machine, g.n]));
  h += cols.map((c, i) => {
    const st = encStatus(c);
    const label = groupSize[c.machine] > 1 ? (c.stream || c.machine) : c.name;
    const cls = ["colhead", c.missing ? "missing" : !c.online ? "offline" : ""].join(" ");
    const tip = [c.name, c.ip_addr, c.missing ? "no es veu a la xarxa" : !c.online ? "fa estona que no es veu" : "",
      st ? `encoder Magewell: ${STATUS_LABEL[st]}` : ""].filter(Boolean).join(" · ");
    return `<th class="${cls}" data-c="${i}" title="${esc(tip)}"><span class="vlabel">${st ? `<i class="dot st-${st}"></i>` : ""}${esc(label)}</span></th>`;
  }).join("");
  h += `</tr></thead><tbody>`;
  h += rows.map((d) => {
    const sig = d.signal || {};
    const cur = d.ndi?.name;
    const sub = d.is_online
      ? `${cur ? "◂ " + cur : "sense font"}${sig.locked && sig.label ? " · " + sig.label : ""}`
      : "no respon";
    return `<tr class="${d.is_online ? "" : "offline"}" data-r="${esc(d.id)}">
      <th class="rowhead" title="${esc(d.name)} · ${esc(d.ip)}"><div class="rname"><i class="dot st-${d.status}"></i>${esc(d.name)}</div>
        <div class="rsub">${esc(sub)}</div></th>` +
      cols.map((c, i) => `<td class="cell ${cellState(d, c)}" data-c="${i}" title="${esc(d.name)} ◂ ${esc(c.name)}"></td>`).join("") +
      `</tr>`;
  }).join("");
  h += `</tbody>`;
  table.innerHTML = h;
  table._cols = cols;
  if (S.hoverCol != null) highlightCol(S.hoverCol);
}

function highlightCol(i) {
  $$("#matrix .hl").forEach((el) => el.classList.remove("hl"));
  S.hoverCol = i;
  if (i == null) return;
  $$(`#matrix [data-c="${i}"]`).forEach((el) => el.classList.add("hl"));
}

async function routeClick(td) {
  const table = $("#matrix");
  const tr = td.closest("tr");
  const d = S.devices.get(tr.dataset.r);
  const c = table._cols[Number(td.dataset.c)];
  if (!d || !c) return;
  if (!S.unlocked) {
    table.classList.remove("shake"); void table.offsetWidth; table.classList.add("shake");
    toast("Matriu bloquejada: prem «Bloquejat · clica per editar» per enrutar");
    return;
  }
  if (!d.is_online) { toast(`'${d.name}' no respon`, true); return; }
  if (sameSrc(d.ndi?.name, c.name)) { toast(`'${d.name}' ja rep '${c.name}'`); return; }
  if (S.pending.has(d.id)) return;
  touchLock();
  S.pending.set(d.id, c.name);
  renderMatrix();
  try {
    const r = await fetch("/api/routing/route", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rx: d.id, tx: c.name }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    if (j.device) S.devices.set(j.device.id, j.device);
    if (!j.confirmed) toast(`L'equip ha acceptat el canvi però encara reporta una altra font`, true);
  } catch (e) {
    S.routeErr = { rx: d.id, tx: c.name, until: Date.now() + 6000 };
    setTimeout(() => S.page === "routing" && renderMatrix(), 6100);
    toast(e.message, true);
  } finally {
    S.pending.delete(d.id);
    renderMatrix();
  }
}

async function refreshSources(btn) {
  btn.disabled = true;
  try {
    const r = await fetch("/api/routing/refresh", { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    S.routing = await r.json();
    renderMatrix();
  } catch (e) { toast(`No s'han pogut refrescar les fonts: ${e.message}`, true); }
  finally { btn.disabled = false; }
}

/* ------------------------------------------------------------------ escaneig */
function renderScan() {
  const bar = $("#scanbar");
  const sc = S.scan;
  const btn = $("#btn-scan");
  if (!sc || !sc.started) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  btn.disabled = sc.running;
  btn.textContent = sc.running ? "Escanejant…" : "Escanejar xarxa";
  $("#scan-progress").style.width = `${Math.round((sc.progress || 0) * 100)}%`;
  $("#scan-progress").parentElement.classList.toggle("hidden", !sc.running);
  if (sc.running) {
    $("#scan-text").textContent = `Escanejant la xarxa… ${Math.round((sc.progress || 0) * 100)}%`;
  } else if (sc.error) {
    $("#scan-text").textContent = `Error a l'escaneig: ${sc.error}`;
  } else {
    const mw = (sc.found || []).filter((h) => h.kind === "mwapi").length;
    const other = (sc.found || []).filter((h) => h.kind === "magewell-other").length;
    const t = sc.finished ? new Date(sc.finished).toLocaleTimeString() : "";
    $("#scan-text").textContent = `Últim escaneig ${t}: ${mw} Magewell compatibles` +
      (other ? `, ${other} Magewell amb API no compatible` : "") +
      (sc.new_devices ? `, ${sc.new_devices} nous` : "") +
      ` · ${sc.hosts_scanned} IP${sc.hosts_scanned === 1 ? "" : "s"} a ${(sc.targets || []).join(", ")}`;
  }
}

async function startScan() {
  try {
    const r = await fetch("/api/discovery/scan", { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (e) { toast(`No s'ha pogut iniciar l'escaneig: ${e.message}`, true); }
}

/* ------------------------------------------------------------------ calaix */
function openDrawer(mode, title) {
  S.drawerMode = mode;
  $("#drawer-title").textContent = title;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#backdrop").classList.remove("hidden");
}
function closeDrawer() {
  S.drawerMode = null; S.openDevice = null;
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#backdrop").classList.add("hidden");
}

function kv(rows) {
  return `<dl class="kv">${rows.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
}

async function renderDeviceDrawer(id, loadRaw = true) {
  const d = S.devices.get(id);
  if (!d) { closeDrawer(); return; }
  S.openDevice = id;
  if (S.drawerMode !== "device") openDrawer("device", d.name); else $("#drawer-title").textContent = d.name;
  const sig = d.signal || {}, n = d.ndi || {}, e = d.expected || {};
  const body = $("#drawer-body");
  const rawBox = body.querySelector("#raw") ? body.querySelector("#raw").outerHTML : `<pre class="raw" id="raw">Carregant…</pre>`;
  body.innerHTML = `
    <div class="row-actions">
      <a class="btn" href="${webUrl(d)}" target="_blank" rel="noopener">Obrir web de l'equip</a>
      ${d.source === "discovered" ? `<button class="btn danger" id="btn-forget">Oblidar equip</button>` : ""}
    </div>
    ${d.issues?.length && d.status !== "OK" ? `<ul class="issues">${d.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
    <h4>Equip</h4>
    ${kv([["Estat", STATUS_LABEL[d.status]], ["IP", `${d.ip}:${d.port}`], ["Model", d.model], ["Rol", d.role], ["Núm. de sèrie", d.serial],
         ["Firmware", d.firmware], ["Revisió HW", d.hw_revision], ["MAC", d.mac], ["Enllaç Ethernet", d.link_speed],
         ["Ubicació", d.location], ["Origen", d.source === "manual" ? "config.yaml" : "descobert"],
         ["Temperatura", d.temperature_c != null ? `${d.temperature_c} °C` : null], ["CPU", d.cpu_usage != null ? `${d.cpu_usage}%` : null],
         ["Memòria", d.memory_usage != null ? `${d.memory_usage}%` : null], ["Ventilador", d.fan_rpm ? `${d.fan_rpm} rpm` : null],
         ["Temps encès", fmtUptime(d.uptime_s)], ["Sortida", d.output_state], ["Temps resposta", d.response_time_ms != null ? `${d.response_time_ms} ms` : null],
         ["Últim contacte", d.last_seen ? new Date(d.last_seen).toLocaleString() : "mai"], ["Error", d.error_message]])}
    <h4>${d.role === "Decoder" ? "Recepció NDI" : "Senyal d'entrada"}</h4>
    ${kv([["Senyal", sig.locked ? "Sí" : "No"], ["Estat cru", sig.state], ["Format", sig.label], ["Resolució", sig.width ? `${sig.width}x${sig.height}` : null],
         ["Freqüència", sig.frame_rate], ["Entrellaçat", sig.interlaced == null ? null : sig.interlaced ? "Sí" : "No"],
         ["Color", sig.color_format], ["Mostreig", sig.sampling], ["Profunditat", sig.color_depth ? `${sig.color_depth} bit` : null],
         ["HDCP", sig.hdcp], ["Àudio", sig.audio]])}
    <h4>NDI</h4>
    ${kv([[d.role === "Decoder" ? "Font" : "Nom del flux", n.name], ["Activat", n.enabled == null ? null : n.enabled ? "Sí" : "No"],
         ["Connectat", n.connected == null ? null : n.connected ? "Sí" : "No"], ["Receptors", n.num_clients],
         ["Bitrate vídeo", n.video_bitrate_kbps != null ? `${(n.video_bitrate_kbps / 1000).toFixed(1)} Mb/s` : null],
         ["Frames perduts (v/a)", n.video_drop_frames != null ? `${n.video_drop_frames} / ${n.audio_drop_frames ?? 0}` : null],
         ["Tally", [n.tally_program && "PGM", n.tally_preview && "PVW"].filter(Boolean).join(" ") || null]])}
    <h4>Estat esperat</h4>
    ${kv(Object.entries(e).filter(([, v]) => v !== null).map(([k, v]) => [k, String(v)]))}
    <h4>Resposta crua de l'API</h4>
    ${rawBox}`;
  const fb = $("#btn-forget");
  if (fb) fb.onclick = () => forgetDevice(d);
  if (loadRaw) {
    try {
      const r = await fetch(`/api/devices/${encodeURIComponent(id)}/raw`);
      const j = await r.json();
      const box = $("#raw");
      if (box) box.textContent = Object.keys(j).length ? JSON.stringify(j, null, 2) : "Encara no hi ha dades (equip sense resposta).";
    } catch (_) {}
  }
}

async function forgetDevice(d) {
  if (!confirm(`Oblidar '${d.name}' (${d.ip})? Si torna a aparèixer en un escaneig, s'afegirà de nou.`)) return;
  const r = await fetch(`/api/devices/${encodeURIComponent(d.id)}`, { method: "DELETE" });
  if (r.ok) { closeDrawer(); toast("Equip oblidat"); } else toast((await r.json()).detail || "Error", true);
}

function renderAlertsBadge() {
  const b = $("#alerts-badge");
  const n = S.alerts.filter((a) => a.severity !== "info").length;
  b.textContent = S.alerts.length;
  b.classList.toggle("hot", n > 0);
}

function renderAlertsDrawer() {
  const body = $("#drawer-body");
  body.innerHTML = `<div class="row-actions"><button class="btn" id="btn-clear-alerts">Netejar historial</button>
    <span class="muted small">També es desa a data/events.log</span></div>` +
    (S.alerts.length ? S.alerts.map((a) => `<div class="alert-item ${esc(a.severity)}">
      <div>${esc(a.message)}</div>
      <div class="meta">${new Date(a.timestamp).toLocaleString()} · ${esc(a.ip)}</div></div>`).join("")
      : `<p class="muted">Cap alerta.</p>`);
  $("#btn-clear-alerts").onclick = async () => { await fetch("/api/alerts/clear", { method: "POST" }); };
}

function renderScanDrawer() {
  const sc = S.scan || {};
  const kindTag = { mwapi: `<span class="tag mw">MAGEWELL</span>`, "magewell-other": `<span class="tag mwo">MAGEWELL?</span>`, http: `<span class="tag">HTTP</span>` };
  $("#drawer-body").innerHTML = `
    ${kv([["Subxarxes", (sc.targets || []).join(", ")], ["IPs escanejades", sc.hosts_scanned], ["Inici", sc.started && new Date(sc.started).toLocaleString()],
         ["Final", sc.finished && new Date(sc.finished).toLocaleString()], ["Nous equips", sc.new_devices], ["Error", sc.error]])}
    <p class="muted small"><b>MAGEWELL</b>: respon a l'API /mwapi i es supervisa. <b>MAGEWELL?</b>: la web esmenta Magewell però l'API no és compatible (model diferent: cal capturar-ne les respostes). <b>HTTP</b>: altres equips amb web.</p>
    <table class="hosts">${(sc.found || []).map((h) => `<tr><td>${kindTag[h.kind] || ""}</td><td class="mono"><a class="link" target="_blank" rel="noopener" href="http://${esc(h.ip)}${h.port !== 80 ? ":" + h.port : ""}/">${esc(h.ip)}${h.port !== 80 ? ":" + h.port : ""}</a></td><td class="muted small">${esc(h.detail || "")}</td></tr>`).join("")}</table>`;
}

/* ------------------------------------------------------------------ utilitats */
let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4000);
}

let audioCtx;
function beep() {
  if (!S.f.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = 880; g.gain.value = 0.08;
    o.connect(g); g.connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.25);
  } catch (_) {}
}

async function post(url, btn, okMsg) {
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(url, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    if (okMsg) toast(okMsg);
  } catch (e) {
    toast(e.message, true);
  } finally {
    if (btn) setTimeout(() => (btn.disabled = false), 400);
  }
}

function syncControls() {
  $$("[data-role]").forEach((b) => b.classList.toggle("active", b.dataset.role === S.f.role));
  $$("[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === S.f.view));
  $("#f-search").value = S.f.q;
  $("#f-problems").checked = S.f.problems;
  $("#f-sort").value = S.f.sort;
  $("#f-sound").checked = S.f.sound;
  $("#f-location").value = S.f.location;
}

function bind() {
  $$(".counter").forEach((b) => b.onclick = () => {
    S.f.status = S.f.status === b.dataset.status ? "ALL" : b.dataset.status;
    render();
  });
  $$("[data-role]").forEach((b) => b.onclick = () => { S.f.role = b.dataset.role; syncControls(); savePrefs(); renderDevices(); });
  $$("[data-view]").forEach((b) => b.onclick = () => { S.f.view = b.dataset.view; syncControls(); savePrefs(); renderDevices(); });
  $("#f-location").onchange = (e) => { S.f.location = e.target.value; savePrefs(); renderDevices(); };
  $("#f-search").oninput = (e) => { S.f.q = e.target.value.trim(); renderDevices(); };
  $("#f-problems").onchange = (e) => { S.f.problems = e.target.checked; savePrefs(); renderDevices(); };
  $("#f-sort").onchange = (e) => { S.f.sort = e.target.value; savePrefs(); renderDevices(); };
  $("#f-sound").onchange = (e) => { S.f.sound = e.target.checked; savePrefs(); if (S.f.sound) beep(); };

  $("#btn-scan").onclick = startScan;
  $("#btn-poll").onclick = (e) => post("/api/poll-now", e.currentTarget);
  $("#btn-reload").onclick = (e) => post("/api/reload-config", e.currentTarget, "Configuració recarregada");
  $("#btn-alerts").onclick = () => { openDrawer("alerts", "Alertes"); renderAlertsDrawer(); };
  $("#btn-scan-details").onclick = () => { openDrawer("scan", "Resultat de l'escaneig"); renderScanDrawer(); };
  $("#backdrop").onclick = closeDrawer;
  $$("[data-close]").forEach((b) => (b.onclick = closeDrawer));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  $("#devices").addEventListener("click", (e) => {
    if (e.target.closest("[data-stop]")) return;
    const el = e.target.closest("[data-id]");
    if (el) renderDeviceDrawer(el.dataset.id);
  });

  // Enrutament
  $$("[data-page]").forEach((b) => (b.onclick = () => setPage(b.dataset.page)));
  $("#btn-lock").onclick = () => setUnlocked(!S.unlocked);
  $("#btn-refresh-sources").onclick = (e) => refreshSources(e.currentTarget);
  $("#r-search").oninput = (e) => { S.r.q = e.target.value.trim(); renderMatrix(); };
  $("#r-offline").onchange = (e) => { S.r.showOffline = e.target.checked; renderMatrix(); };
  const matrix = $("#matrix");
  matrix.addEventListener("click", (e) => { const td = e.target.closest("td.cell"); if (td) routeClick(td); });
  matrix.addEventListener("mouseover", (e) => {
    const cell = e.target.closest("[data-c]");
    const i = cell ? cell.dataset.c : null;
    if (i !== S.hoverCol) highlightCol(i);
  });
  matrix.addEventListener("mouseleave", () => highlightCol(null));

  // Avís si deixen d'arribar dades (servidor aturat, PC suspès...)
  setInterval(() => {
    const stale = S.lastEvent && Date.now() - S.lastEvent > Math.max(20000, S.interval * 5000);
    $("#stale").classList.toggle("hidden", !stale);
  }, 2000);
}

document.addEventListener("DOMContentLoaded", () => {
  loadPrefs();
  syncControls();
  bind();
  setPage(S.page);
  connect();
});
