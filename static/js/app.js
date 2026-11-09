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
  } catch (_) { /* sense emmagatzematge: valors per defecte */ }
}
function savePrefs() {
  try {
    const { role, location, problems, sort, view, sound } = S.f;
    localStorage.setItem("nms-prefs", JSON.stringify({ role, location, problems, sort, view, sound }));
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
  }
}

function setLive(on) {
  $("#live-dot").className = "live-dot " + (on ? "on" : "err");
}

/* ------------------------------------------------------------------ render principal */
function render() {
  renderCounters();
  renderLocations();
  renderDevices();
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
  connect();
});
