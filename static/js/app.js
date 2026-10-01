/**
 * Magewell Mini-NMS Client Application
 * Real-time SSE telemetry receiver, drift monitoring, and multiview rendering.
 */

// App State
const state = {
  devices: [],
  summary: {
    total_devices: 0,
    online_count: 0,
    offline_count: 0,
    ok_count: 0,
    warning_count: 0,
    no_signal_count: 0,
    last_poll_timestamp: null,
  },
  alerts: [],
  filterLocation: "ALL",
  filterStatus: "ALL",
  searchQuery: "",
  viewMode: "grid", // 'grid' or 'list'
  connected: false,
};

// DOM Elements
const elements = {
  connectionStatus: document.getElementById("connection-status"),
  devicesContainer: document.getElementById("devices-container"),
  lastUpdated: document.getElementById("last-updated"),
  searchQueryInput: document.getElementById("search-query"),
  alertsList: document.getElementById("alerts-list"),
  alertsBadge: document.getElementById("alerts-badge"),
  alertsDrawer: document.getElementById("alerts-drawer"),
  btnPollNow: document.getElementById("btn-poll-now"),
  btnReloadConfig: document.getElementById("btn-reload-config"),
  btnClearAlerts: document.getElementById("btn-clear-alerts"),
  btnToggleAlerts: document.getElementById("btn-toggle-alerts"),
  btnCloseAlerts: document.getElementById("btn-close-alerts"),
  btnViewGrid: document.getElementById("btn-view-grid"),
  btnViewList: document.getElementById("btn-view-list"),
  
  // Counters
  countTotal: document.getElementById("count-total"),
  countOnline: document.getElementById("count-online"),
  countOk: document.getElementById("count-ok"),
  countWarning: document.getElementById("count-warning"),
  countNoSignal: document.getElementById("count-no-signal"),
  countOffline: document.getElementById("count-offline"),
};

// Initialize SSE Connection
function initSSE() {
  const evtSource = new EventSource("/api/events");

  evtSource.onopen = () => {
    state.connected = true;
    updateConnectionUI(true);
  };

  evtSource.onerror = (err) => {
    state.connected = false;
    updateConnectionUI(false);
  };

  evtSource.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data);
      handleServerEvent(payload);
    } catch (err) {
      console.error("Error parsing SSE data:", err, e.data);
    }
  };
}

function updateConnectionUI(isConnected) {
  if (!elements.connectionStatus) return;
  if (isConnected) {
    elements.connectionStatus.innerHTML = `
      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-900/60 text-emerald-400 border border-emerald-700/50">
        <span class="w-1.5 h-1.5 mr-1.5 bg-emerald-400 rounded-full animate-pulse"></span>
        SSE LIVE
      </span>
    `;
  } else {
    elements.connectionStatus.innerHTML = `
      <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-900/60 text-rose-400 border border-rose-700/50">
        <span class="w-1.5 h-1.5 mr-1.5 bg-rose-500 rounded-full"></span>
        RECONNECTING...
      </span>
    `;
  }
}

function handleServerEvent(payload) {
  const { type, data } = payload;

  switch (type) {
    case "snapshot":
      state.devices = data.devices || [];
      state.summary = data.summary || state.summary;
      state.alerts = data.alerts || [];
      renderUI();
      break;

    case "cycle_complete":
      state.devices = data.devices || [];
      state.summary = data.summary || state.summary;
      renderUI();
      break;

    case "device_update":
      const index = state.devices.findIndex((d) => d.id === data.id);
      if (index !== -1) {
        state.devices[index] = data;
      } else {
        state.devices.push(data);
      }
      renderUI();
      break;

    case "alert":
      state.alerts.unshift(data);
      if (state.alerts.length > 50) state.alerts.pop();
      renderAlerts();
      playAlertNotification(data.severity);
      break;

    case "alerts_cleared":
      state.alerts = [];
      renderAlerts();
      break;
  }
}

function playAlertNotification(severity) {
  if (severity === "error" || severity === "warning") {
    // Gentle audio or title pulse if document is hidden
    if (document.hidden) {
      document.title = `[ALERT] Magewell Mini-NMS`;
      setTimeout(() => {
        document.title = "Magewell Pro Convert - Mini NMS";
      }, 3000);
    }
  }
}

// Rendering Logic
function renderUI() {
  renderCounters();
  renderDevices();
  renderAlerts();
  updateTimestamp();
}

function renderCounters() {
  const s = state.summary;
  if (elements.countTotal) elements.countTotal.textContent = s.total_devices;
  if (elements.countOnline) elements.countOnline.textContent = s.online_count;
  if (elements.countOk) elements.countOk.textContent = s.ok_count;
  if (elements.countWarning) elements.countWarning.textContent = s.warning_count;
  if (elements.countNoSignal) elements.countNoSignal.textContent = s.no_signal_count;
  if (elements.countOffline) elements.countOffline.textContent = s.offline_count;
}

function updateTimestamp() {
  if (!elements.lastUpdated) return;
  const ts = state.summary.last_poll_timestamp || new Date().toISOString();
  const date = new Date(ts);
  elements.lastUpdated.textContent = `Últim sondeig: ${date.toLocaleTimeString()}`;
}

function getFilteredDevices() {
  return state.devices.filter((dev) => {
    // Location Filter
    if (state.filterLocation !== "ALL") {
      if (state.filterLocation === "DECODERS") {
        if (dev.role !== "Decoder") return false;
      } else if (dev.location !== state.filterLocation) {
        return false;
      }
    }

    // Status Filter
    if (state.filterStatus !== "ALL") {
      if (state.filterStatus === "ALERTS_ONLY") {
        if (dev.status === "OK") return false;
      } else if (dev.status !== state.filterStatus) {
        return false;
      }
    }

    // Search Query
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      const matchName = dev.name.toLowerCase().includes(q);
      const matchIp = dev.ip.toLowerCase().includes(q);
      const matchModel = dev.model.toLowerCase().includes(q);
      const matchNdi = (dev.ndi_name || "").toLowerCase().includes(q);
      if (!matchName && !matchIp && !matchModel && !matchNdi) return false;
    }

    return true;
  });
}

function renderDevices() {
  if (!elements.devicesContainer) return;
  const filtered = getFilteredDevices();

  if (filtered.length === 0) {
    elements.devicesContainer.innerHTML = `
      <div class="col-span-full py-16 text-center text-slate-500">
        <svg class="w-12 h-12 mx-auto mb-3 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p class="text-base font-medium">No s'ha trobat cap dispositiu amb els filtres actius</p>
        <p class="text-xs text-slate-600 mt-1">Prova de canviar la cerca o netejar els filtres de la barra superior.</p>
      </div>
    `;
    return;
  }

  if (state.viewMode === "grid") {
    elements.devicesContainer.className = "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4";
    elements.devicesContainer.innerHTML = filtered.map((d) => renderDeviceCardGrid(d)).join("");
  } else {
    elements.devicesContainer.className = "space-y-2.5";
    elements.devicesContainer.innerHTML = filtered.map((d) => renderDeviceCardList(d)).join("");
  }
}

function getStatusBadge(status) {
  switch (status) {
    case "OK":
      return `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-emerald-950 text-emerald-400 border border-emerald-800">
        <span class="w-1.5 h-1.5 mr-1 bg-emerald-400 rounded-full"></span> OK
      </span>`;
    case "WARNING":
      return `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-950 text-amber-400 border border-amber-700 animate-pulse">
        <span class="w-1.5 h-1.5 mr-1 bg-amber-400 rounded-full"></span> DRIFT
      </span>`;
    case "NO_SIGNAL":
      return `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-rose-950 text-rose-400 border border-rose-800 animate-pulse">
        <span class="w-1.5 h-1.5 mr-1 bg-rose-500 rounded-full"></span> NO SIGNAL
      </span>`;
    case "OFFLINE":
    default:
      return `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-slate-800 text-slate-400 border border-slate-700">
        <span class="w-1.5 h-1.5 mr-1 bg-slate-500 rounded-full"></span> OFFLINE
      </span>`;
  }
}

function renderDeviceCardGrid(d) {
  const statusClass = `status-${d.status.toLowerCase()}`;
  const isOnline = d.is_online;
  const sig = d.signal || {};
  const exp = d.expected || {};

  // Video format formatting
  let videoDisplay = "No Signal";
  if (sig.locked) {
    const res = sig.width && sig.height ? `${sig.width}x${sig.height}` : "Sense resolució";
    const fps = sig.frame_rate ? `@ ${sig.frame_rate}p` : "";
    const col = sig.color_format ? ` (${sig.color_format})` : "";
    videoDisplay = `${res} ${fps}${col}`;
  }

  // Expected vs actual text
  const expRes = exp.width && exp.height ? `${exp.width}x${exp.height}` : "";
  const expFps = exp.frame_rate ? `@ ${exp.frame_rate}p` : "";
  const expectedDisplay = `${expRes} ${expFps}`.trim() || "Qualsevol";

  // Temperature color
  let tempColor = "text-slate-400";
  if (d.temperature_c !== null) {
    if (d.temperature_c > 65) tempColor = "text-rose-400 font-bold";
    else if (d.temperature_c > 55) tempColor = "text-amber-400 font-medium";
    else tempColor = "text-emerald-400";
  }

  const hasDrifts = d.drifts && d.drifts.length > 0;

  return `
    <div class="status-card bg-slate-900/90 rounded-lg border ${statusClass} p-3.5 flex flex-col justify-between shadow-lg relative overflow-hidden">
      <!-- Card Top: Name, Location, Status Badge -->
      <div>
        <div class="flex items-start justify-between gap-2 mb-2">
          <div class="min-w-0">
            <h3 class="text-sm font-semibold text-slate-100 truncate" title="${d.name}">${d.name}</h3>
            <div class="flex items-center gap-1.5 text-xs text-slate-400 mt-0.5">
              <span class="px-1.5 py-0.2 bg-slate-800 rounded text-[11px] font-mono text-slate-300">${d.location || 'LAN'}</span>
              <span class="text-slate-500">•</span>
              <span class="text-[11px] text-slate-400 truncate">${d.role || 'Unit'}</span>
            </div>
          </div>
          <div>${getStatusBadge(d.status)}</div>
        </div>

        <!-- IP & Model Bar -->
        <div class="flex items-center justify-between text-xs py-1.5 border-y border-slate-800/80 my-2 text-slate-400">
          <a href="http://${d.ip}:${d.port}" target="_blank" class="font-mono text-indigo-400 hover:text-indigo-300 hover:underline flex items-center gap-1">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
            ${d.ip}
          </a>
          <span class="text-[11px] text-slate-400 truncate max-w-[120px]" title="${d.model}">${d.model}</span>
        </div>

        <!-- Video Signal Lock & Format -->
        <div class="bg-slate-950/70 rounded p-2 mb-2 border border-slate-800/60">
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="text-slate-400 flex items-center gap-1">
              ${sig.locked
                ? `<svg class="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd" /></svg><span class="font-semibold text-emerald-400">SIGNAL LOCK</span>`
                : `<svg class="w-3.5 h-3.5 text-rose-500" fill="currentColor" viewBox="0 0 20 20"><path d="M10 2a5 5 0 00-5 5v2a2 2 0 00-2 2v5a2 2 0 002 2h10a2 2 0 002-2v-5a2 2 0 00-2-2H7V7a3 3 0 016 0v2h2V7a5 5 0 00-5-5z" /></svg><span class="font-semibold text-rose-500">NO SIGNAL</span>`
              }
            </span>
            <span class="font-mono text-xs font-semibold ${sig.locked ? 'text-slate-200' : 'text-slate-500'}">${videoDisplay}</span>
          </div>

          <!-- Expected vs Live Status -->
          <div class="text-[11px] text-slate-400 flex justify-between border-t border-slate-900 pt-1 mt-1">
            <span class="text-slate-500">Expected:</span>
            <span class="font-mono text-slate-400">${expectedDisplay}</span>
          </div>
        </div>

        <!-- Drift Warning Banners -->
        ${hasDrifts ? `
          <div class="mb-2.5 p-1.5 rounded bg-amber-950/50 border border-amber-800/80 text-[11px] text-amber-300 space-y-0.5">
            ${d.drifts.map(drift => `
              <div class="flex items-start gap-1">
                <span class="text-amber-400 font-bold">⚠</span>
                <span class="leading-tight">${drift}</span>
              </div>
            `).join("")}
          </div>
        ` : ''}
      </div>

      <!-- Card Bottom: Telemetry Metrics -->
      <div class="pt-2 border-t border-slate-800/80 grid grid-cols-3 gap-1 text-[11px] text-slate-400">
        <div>
          <span class="text-slate-500 block text-[10px]">TEMP</span>
          <span class="${tempColor}">${d.temperature_c !== null ? `${d.temperature_c}°C` : '--'}</span>
        </div>
        <div>
          <span class="text-slate-500 block text-[10px]">NDI / STREAM</span>
          <span class="text-slate-300 font-mono truncate block text-[10px]" title="${d.ndi_name || 'N/A'}">${d.ndi_name || '--'}</span>
        </div>
        <div class="text-right">
          <span class="text-slate-500 block text-[10px]">PING</span>
          <span class="font-mono text-slate-400">${isOnline ? `${d.response_time_ms}ms` : '--'}</span>
        </div>
      </div>
    </div>
  `;
}

function renderDeviceCardList(d) {
  const statusClass = `status-${d.status.toLowerCase()}`;
  const sig = d.signal || {};
  const exp = d.expected || {};
  const isOnline = d.is_online;

  let videoDisplay = "Sense Senyal";
  if (sig.locked) {
    videoDisplay = `${sig.width}x${sig.height} @ ${sig.frame_rate}p`;
  }

  const expDisplay = `${exp.width}x${exp.height} @ ${exp.frame_rate}p`;

  return `
    <div class="status-card bg-slate-900 border ${statusClass} rounded-lg p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
      <div class="flex items-center gap-3 min-w-[240px]">
        <div>${getStatusBadge(d.status)}</div>
        <div>
          <h4 class="font-semibold text-slate-100">${d.name}</h4>
          <span class="text-slate-400 font-mono text-[11px]">${d.ip} • ${d.model} (${d.location})</span>
        </div>
      </div>

      <div class="flex items-center gap-6">
        <div>
          <span class="text-slate-500 text-[10px] block">SIGNAL STATUS</span>
          <span class="font-mono font-medium ${sig.locked ? 'text-emerald-400' : 'text-rose-400'}">${videoDisplay}</span>
        </div>

        <div>
          <span class="text-slate-500 text-[10px] block">EXPECTED</span>
          <span class="font-mono text-slate-400">${expDisplay}</span>
        </div>

        <div>
          <span class="text-slate-500 text-[10px] block">TEMP</span>
          <span class="font-mono ${d.temperature_c > 60 ? 'text-amber-400' : 'text-slate-300'}">${d.temperature_c !== null ? `${d.temperature_c}°C` : '--'}</span>
        </div>

        <div>
          <span class="text-slate-500 text-[10px] block">NDI STREAM</span>
          <span class="font-mono text-slate-300 truncate max-w-[120px] block">${d.ndi_name || '--'}</span>
        </div>

        <div>
          <span class="text-slate-500 text-[10px] block">LATÈNCIA</span>
          <span class="font-mono text-slate-400">${isOnline ? `${d.response_time_ms}ms` : '--'}</span>
        </div>

        <div>
          <a href="http://${d.ip}:${d.port}" target="_blank" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-indigo-300 rounded text-xs font-medium border border-slate-700 transition">
            Obrir GUI
          </a>
        </div>
      </div>
    </div>
  `;
}

function renderAlerts() {
  if (!elements.alertsList) return;
  const count = state.alerts.length;
  if (elements.alertsBadge) {
    elements.alertsBadge.textContent = count;
    elements.alertsBadge.className = count > 0 
      ? "px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-600 text-white animate-pulse"
      : "px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-slate-700 text-slate-300";
  }

  if (count === 0) {
    elements.alertsList.innerHTML = `
      <div class="py-12 text-center text-slate-500 text-xs">
        <svg class="w-8 h-8 mx-auto mb-2 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" /></svg>
        No hi ha cap alerta activa. La flota funciona correctament.
      </div>
    `;
    return;
  }

  elements.alertsList.innerHTML = state.alerts.map((a) => {
    let borderClass = "border-amber-700 bg-amber-950/30 text-amber-200";
    if (a.severity === "error") {
      borderClass = "border-rose-700 bg-rose-950/30 text-rose-200";
    } else if (a.severity === "info") {
      borderClass = "border-emerald-700 bg-emerald-950/30 text-emerald-200";
    }

    const time = new Date(a.timestamp).toLocaleTimeString();

    return `
      <div class="p-2.5 rounded border ${borderClass} text-xs mb-2">
        <div class="flex items-center justify-between mb-1">
          <span class="font-bold font-mono uppercase text-[10px]">${a.severity}</span>
          <span class="text-slate-400 text-[10px] font-mono">${time}</span>
        </div>
        <p class="font-medium mb-1">${a.message}</p>
        <div class="text-[10px] text-slate-400 font-mono">${a.device_name} (${a.ip})</div>
      </div>
    `;
  }).join("");
}

// Action Handlers
async function triggerPollNow() {
  if (!elements.btnPollNow) return;
  const originalText = elements.btnPollNow.innerHTML;
  elements.btnPollNow.innerHTML = `
    <svg class="animate-spin w-4 h-4 mr-1 text-white" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
    Sondejant...
  `;
  elements.btnPollNow.disabled = true;

  try {
    const res = await fetch("/api/poll-now", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.error("Error triggering poll:", err);
  } finally {
    setTimeout(() => {
      elements.btnPollNow.innerHTML = originalText;
      elements.btnPollNow.disabled = false;
    }, 500);
  }
}

async function triggerReloadConfig() {
  if (!elements.btnReloadConfig) return;
  const originalText = elements.btnReloadConfig.innerHTML;
  elements.btnReloadConfig.innerHTML = `Recarregant...`;
  elements.btnReloadConfig.disabled = true;

  try {
    const res = await fetch("/api/reload-config", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    alert(`Configuració recarregada: ${data.device_count} dispositius actius.`);
  } catch (err) {
    alert(`Error recarregant YAML: ${err.message}`);
  } finally {
    elements.btnReloadConfig.innerHTML = originalText;
    elements.btnReloadConfig.disabled = false;
  }
}

async function clearAlerts() {
  try {
    await fetch("/api/alerts/clear", { method: "POST" });
    state.alerts = [];
    renderAlerts();
  } catch (err) {
    console.error("Error clearing alerts:", err);
  }
}

// Setup Event Listeners
function setupEventListeners() {
  if (elements.btnPollNow) elements.btnPollNow.addEventListener("click", triggerPollNow);
  if (elements.btnReloadConfig) elements.btnReloadConfig.addEventListener("click", triggerReloadConfig);
  if (elements.btnClearAlerts) elements.btnClearAlerts.addEventListener("click", clearAlerts);

  if (elements.searchQueryInput) {
    elements.searchQueryInput.addEventListener("input", (e) => {
      state.searchQuery = e.target.value.trim();
      renderDevices();
    });
  }

  // Filter location buttons
  document.querySelectorAll(".btn-filter-location").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".btn-filter-location").forEach((b) => {
        b.classList.remove("bg-indigo-600", "text-white");
        b.classList.add("bg-slate-800", "text-slate-300");
      });
      btn.classList.add("bg-indigo-600", "text-white");
      btn.classList.remove("bg-slate-800", "text-slate-300");
      state.filterLocation = btn.getAttribute("data-location");
      renderDevices();
    });
  });

  // Filter status buttons
  document.querySelectorAll(".btn-filter-status").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".btn-filter-status").forEach((b) => {
        b.classList.remove("border-indigo-500", "font-bold");
      });
      btn.classList.add("border-indigo-500", "font-bold");
      state.filterStatus = btn.getAttribute("data-status");
      renderDevices();
    });
  });

  // View Mode
  if (elements.btnViewGrid) {
    elements.btnViewGrid.addEventListener("click", () => {
      state.viewMode = "grid";
      elements.btnViewGrid.classList.add("bg-indigo-600", "text-white");
      elements.btnViewList.classList.remove("bg-indigo-600", "text-white");
      renderDevices();
    });
  }
  if (elements.btnViewList) {
    elements.btnViewList.addEventListener("click", () => {
      state.viewMode = "list";
      elements.btnViewList.classList.add("bg-indigo-600", "text-white");
      elements.btnViewGrid.classList.remove("bg-indigo-600", "text-white");
      renderDevices();
    });
  }

  // Alerts Drawer toggle
  if (elements.btnToggleAlerts && elements.alertsDrawer) {
    elements.btnToggleAlerts.addEventListener("click", () => {
      elements.alertsDrawer.classList.toggle("translate-x-full");
    });
  }
  if (elements.btnCloseAlerts && elements.alertsDrawer) {
    elements.btnCloseAlerts.addEventListener("click", () => {
      elements.alertsDrawer.classList.add("translate-x-full");
    });
  }
}

// Bootstrap on DOM Ready
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  initSSE();
});
