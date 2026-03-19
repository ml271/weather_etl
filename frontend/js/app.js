/**
 * Weather Station Dashboard
 */

const API = "/api";   // Nginx proxy → backend:8000

// City / coords from URL params (?city=München&lat=48.13&lon=11.58)
const _params = new URLSearchParams(window.location.search);
const CITY = _params.get("city") || null;
const LAT  = _params.get("lat")  ? parseFloat(_params.get("lat"))  : null;
const LON  = _params.get("lon")  ? parseFloat(_params.get("lon"))  : null;

// Append ?city= to API paths if provided
function apiPath(path) {
  if (!CITY) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}city=${encodeURIComponent(CITY)}`;
}

const WMO_ICONS = {
  0:"☀️",1:"🌤️",2:"⛅",3:"☁️",
  45:"🌫️",48:"🌫️",
  51:"🌦️",53:"🌦️",55:"🌧️",
  61:"🌧️",63:"🌧️",65:"🌧️",
  71:"❄️",73:"❄️",75:"❄️",77:"🌨️",
  80:"🌦️",81:"🌧️",82:"⛈️",
  85:"🌨️",86:"🌨️",
  95:"⛈️",96:"⛈️",99:"⛈️",
};

const SEVERITY_ICONS = { danger:"🚨", warning:"⚠️", info:"ℹ️" };
const WEEKDAYS = ["SUN","MON","TUE","WED","THU","FRI","SAT"];

let currentPlotHours = 96;
let selectedSoilT = new Set(["0"]);
let selectedSoilM = new Set(["0-1"]);

window.toggleSoilDepth = function(type, depth) {
  const set = type === "T" ? selectedSoilT : selectedSoilM;
  if (set.has(depth)) {
    if (set.size > 1) set.delete(depth); // keep at least one selected
  } else {
    set.add(depth);
  }
  // Update button visual state
  document.querySelectorAll(`.legend-btn[data-type="${type}"]`).forEach(btn => {
    const on = set.has(btn.dataset.depth);
    btn.classList.toggle("active", on);
    btn.classList.toggle("inactive", !on);
  });
  loadHourlyPlot(currentPlotHours);
};

// ─────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────

function fmt(val, unit = "", fallback = "—") {
  if (val === null || val === undefined) return fallback;
  return `${parseFloat(val).toFixed(1)}${unit}`;
}

function fmtInt(val, unit = "", fallback = "—") {
  if (val === null || val === undefined) return fallback;
  return `${Math.round(val)}${unit}`;
}

function getIcon(code) {
  return WMO_ICONS[code] ?? "🌡️";
}

function fmtDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr + "T12:00:00");
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

// ─────────────────────────────────────────────────────
// Render: Summary
// ─────────────────────────────────────────────────────

function renderSummary(data) {
  document.getElementById("cityName").textContent = data.city || "—";
  document.getElementById("lastUpdated").textContent =
    data.last_updated
      ? "SYNC " + new Date(data.last_updated).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
      : "NO SYNC";

  const dot = document.getElementById("statusDot");
  dot.className = "status-dot " + (data.today ? "online" : "error");

  renderAlerts(data.active_alerts ?? []);
}

// ─────────────────────────────────────────────────────
// Render: Forecast date range in header
// ─────────────────────────────────────────────────────

function updateForecastRange() {
  const now = new Date();
  const end = new Date(now.getTime() + currentPlotHours * 3600 * 1000);
  const fmt2 = d => d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  document.getElementById("forecastRange").textContent = `${fmt2(now)} – ${fmt2(end)}`;
}

// ─────────────────────────────────────────────────────
// Render: Triggered user warnings
// ─────────────────────────────────────────────────────

const PARAM_LABELS = {
  temperature_max:    "Temp. max",
  temperature_min:    "Temp. min",
  precipitation_sum:  "Precipitation",
  snowfall_sum:       "Snowfall",
  wind_speed_10m_max: "Wind",
  wind_gusts_10m_max: "Gusts",
  uv_index_max:       "UV Index",
};
const PARAM_UNITS = {
  temperature_max: "°C", temperature_min: "°C",
  precipitation_sum: "mm", snowfall_sum: "cm",
  wind_speed_10m_max: "km/h", wind_gusts_10m_max: "km/h",
  uv_index_max: "",
};

function renderTriggered(items) {
  const countEl = document.getElementById("alertCount");
  const listEl  = document.getElementById("triggeredList");
  countEl.textContent = items.length;
  countEl.dataset.count = items.length;

  if (!items.length) {
    listEl.innerHTML = `<div class="no-alerts">No active warnings ✓</div>`;
    return;
  }
  listEl.innerHTML = "";
  items.forEach(item => {
    const chip = document.createElement("div");
    chip.className = "alert-chip warning";
    chip.style.cursor = "pointer";
    chip.title = "Click to edit";
    chip.addEventListener("click", () => {
      window.location.href = `warnings.html?edit=${encodeURIComponent(item.warning_id)}`;
    });

    const header = document.createElement("div");
    header.className = "chip-body";

    const nameEl = document.createElement("span");
    nameEl.className = "chip-name warning";
    nameEl.textContent = item.name.toUpperCase();

    const dateEl = document.createElement("span");
    dateEl.className = "chip-date";
    dateEl.textContent = "📅 " + item.forecast_date;

    header.append(nameEl, dateEl);

    // One line per triggered condition
    (item.conditions || []).forEach(c => {
      const param = c.parameter || "";
      const label = PARAM_LABELS[param] || param;
      const unit  = PARAM_UNITS[param]  || "";
      const actual = c.actual_value != null ? `${parseFloat(c.actual_value).toFixed(1)}${unit}` : "–";
      const thresh = `${c.value}${unit}`;

      const row = document.createElement("span");
      row.className = "chip-msg";
      row.textContent = `${label}: ${actual} (${c.comparator} ${thresh})`;
      header.appendChild(row);
    });

    chip.appendChild(header);
    listEl.appendChild(chip);
  });
}

function renderSavedWarnings(warnings) {
  const el = document.getElementById("savedWarningsList");
  if (!el) return;
  if (!warnings || !warnings.length) {
    el.innerHTML = `<div class="no-alerts">No saved warnings</div>`;
    return;
  }
  el.innerHTML = "";
  warnings.forEach(w => {
    const chip = document.createElement("div");
    chip.className = "alert-chip info";
    chip.style.cursor = "pointer";
    chip.title = "Click to edit";
    chip.addEventListener("click", () => {
      window.location.href = `warnings.html?edit=${encodeURIComponent(w.id)}`;
    });

    const body = document.createElement("div");
    body.className = "chip-body";

    const nameEl = document.createElement("span");
    nameEl.className = "chip-name info";
    nameEl.textContent = w.name.toUpperCase();

    const cityEl = document.createElement("span");
    cityEl.className = "chip-msg";
    cityEl.textContent = w.city;

    body.append(nameEl, cityEl);
    chip.appendChild(body);
    el.appendChild(chip);
  });
}

// ─────────────────────────────────────────────────────
// Render: Generic weather alerts
// ─────────────────────────────────────────────────────

function renderAlerts(alerts) {
  const listEl  = document.getElementById("alertsList");
  const banner  = document.getElementById("alertBanner");

  if (!alerts.length) {
    listEl.innerHTML = `<div class="no-alerts">No weather alerts ✓</div>`;
    banner.style.display = "none";
    return;
  }

  const dangers = alerts.filter(a => a.severity === "danger");
  if (dangers.length > 0) {
    banner.style.display = "block";
    banner.textContent = `⚡ ALERT: ${dangers.map(d => d.alert_name).join(" · ")}`;
  } else {
    banner.style.display = "none";
  }

  listEl.innerHTML = "";
  alerts.forEach(a => {
    const severity = ["danger","warning","info"].includes(a.severity) ? a.severity : "info";
    const chip = document.createElement("div");
    chip.className = `alert-chip ${severity}`;

    const icon = document.createElement("span");
    icon.className = "chip-icon";
    icon.textContent = SEVERITY_ICONS[severity] ?? "⚡";

    const body = document.createElement("div");
    body.className = "chip-body";

    const name = document.createElement("span");
    name.className = `chip-name ${severity}`;
    name.textContent = (a.alert_name ?? "").toUpperCase();

    const msg = document.createElement("span");
    msg.className = "chip-msg";
    msg.textContent = a.message ?? "";

    const dt = document.createElement("span");
    dt.className = "chip-date";
    dt.textContent = a.forecast_date ? "📅 " + a.forecast_date : "";

    body.append(name, msg, dt);
    chip.append(icon, body);
    listEl.appendChild(chip);
  });
}

// ─────────────────────────────────────────────────────
// Render: 7-day Forecast Strip
// ─────────────────────────────────────────────────────

function renderForecast(records) {
  const today = new Date().toISOString().slice(0, 10);
  const row   = document.getElementById("forecastRow");

  row.innerHTML = records.map(r => {
    const dt      = new Date(r.forecast_date + "T12:00:00");
    const weekday = WEEKDAYS[dt.getDay()];
    const isToday = r.forecast_date === today;
    const rain    = parseFloat(r.precipitation_sum) || 0;

    return `
      <div class="forecast-day ${isToday ? "today" : ""}" onclick="openDayModal('${r.forecast_date}')">
        <span class="f-weekday">${isToday ? "TODAY" : weekday}</span>
        <span class="f-icon">${getIcon(r.weather_code)}</span>
        <span class="f-max">${fmt(r.temperature_max, "°")}</span>
        <span class="f-min">${fmt(r.temperature_min, "°")}</span>
        ${rain > 0 ? `<span class="f-rain">💧 ${fmt(rain, "mm")}</span>` : '<span class="f-rain"></span>'}
      </div>
    `;
  }).join("");

}

// ─────────────────────────────────────────────────────
// Day Detail Modal
// ─────────────────────────────────────────────────────

window.openDayModal = function(dateStr) {
  const modal   = document.getElementById("dayModal");
  const img     = document.getElementById("modalPlotImg");
  const loading = document.getElementById("modalLoading");
  const title   = document.getElementById("modalTitle");

  const d  = new Date(dateStr + "T12:00:00");
  const dayNames = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
  title.textContent = `${dayNames[d.getDay()].toUpperCase()}  ·  ${d.toLocaleDateString("en-GB", { day:"2-digit", month:"long", year:"numeric" })}`;

  img.classList.remove("loaded");
  img.src = "";
  loading.style.display = "block";
  loading.textContent = "Loading hourly data...";
  modal.classList.add("open");
  document.body.style.overflow = "hidden";

  img.onload  = () => { loading.style.display = "none"; img.classList.add("loaded"); };
  img.onerror = () => { loading.textContent = "No hourly data for this day."; };
  img.src = `${API}${apiPath(`/charts/day-detail?date=${dateStr}`)}&_t=${Date.now()}`;
};

window.closeDayModal = function() {
  document.getElementById("dayModal").classList.remove("open");
  document.body.style.overflow = "";
};

document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDayModal();
});

// ─────────────────────────────────────────────────────
// Hourly Plot Image
// ─────────────────────────────────────────────────────

function loadHourlyPlot(hours) {
  const img     = document.getElementById("hourlyPlotImg");
  const loading = document.getElementById("hourlyPlotLoading");

  img.classList.remove("loaded");
  img.src = "";  // clear first so browser always fires onload for the new src
  loading.style.display = "block";
  loading.textContent = "Loading chart...";

  const soilT = [...selectedSoilT].sort().join(",");
  const soilM = [...selectedSoilM].sort().join(",");
  const url = `${API}${apiPath(`/charts/hourly-plot?hours=${hours}`)}&soil_t=${encodeURIComponent(soilT)}&soil_m=${encodeURIComponent(soilM)}&_t=${Date.now()}`;

  img.onload = () => {
    loading.style.display = "none";
    img.classList.add("loaded");
  };
  img.onerror = () => {
    loading.textContent = "No data – run ETL job!";
  };
  img.src = url;
}

window.switchPlotHours = function(hours) {
  currentPlotHours = hours;
  document.querySelectorAll(".plot-hours .toggle-btn").forEach(btn => {
    btn.classList.toggle("active", parseInt(btn.dataset.hours) === hours);
  });
  updateForecastRange();
  loadHourlyPlot(hours);
};

// ─────────────────────────────────────────────────────
// Data Fetching
// ─────────────────────────────────────────────────────

async function apiFetch(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function loadSummary() {
  try {
    const data = await apiFetch(apiPath("/summary"));
    renderSummary(data);
  } catch (e) {
    console.error("Summary failed:", e);
    document.getElementById("statusDot").className = "status-dot error";
    document.getElementById("lastUpdated").textContent = "OFFLINE";
  }
}

async function fetchWeatherNow() {
  if (!CITY || LAT == null || LON == null) return false;
  const token = localStorage.getItem("token");
  if (!token) return false;
  const url = `${API}/weather/fetch-now?city=${encodeURIComponent(CITY)}&lat=${LAT}&lon=${LON}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`fetch-now → ${res.status}`);
  return true;
}

async function loadForecast() {
  try {
    const data = await apiFetch(apiPath("/forecast/daily?days=7"));
    renderForecast(data);
  } catch (e) {
    document.getElementById("forecastRow").innerHTML =
      `<div class="forecast-loading">No data – run ETL job!</div>`;
  }
}

async function loadSidebarWarnings() {
  const token = localStorage.getItem("token");
  if (!token || !CITY) return;

  // Triggered warnings
  try {
    const res = await fetch(
      `${API}/warnings/triggered?city=${encodeURIComponent(CITY)}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (res.ok) renderTriggered(await res.json());
  } catch (_) {}

  // Saved warnings
  try {
    const res = await fetch(`${API}/warnings/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) renderSavedWarnings(await res.json());
  } catch (_) {}
}

// ─────────────────────────────────────────────────────
// Init & Auto-Refresh
// ─────────────────────────────────────────────────────

async function init() {
  updateForecastRange();

  // If we have coords, check first whether data exists / is fresh – if not, fetch before rendering
  if (CITY && LAT != null && LON != null) {
    let needsFetch = false;
    try {
      await apiFetch(apiPath("/forecast/daily?days=1"));
      // Data exists — check staleness (re-fetch if last update > 6 hours ago)
      try {
        const summary = await apiFetch(apiPath("/summary"));
        const lu = summary.last_updated ? new Date(summary.last_updated) : null;
        if (!lu || (Date.now() - lu.getTime()) > 6 * 3600 * 1000) {
          needsFetch = true;
        }
      } catch (_) { /* ignore summary errors, proceed with cached data */ }
    } catch (e) {
      if (e.message.includes("404")) needsFetch = true;
    }

    if (needsFetch) {
      document.getElementById("forecastRow").innerHTML =
        `<div class="forecast-loading">⏳ Loading weather data for ${CITY} …</div>`;
      const plotLoading = document.getElementById("hourlyPlotLoading");
      plotLoading.style.display = "block";
      plotLoading.textContent = "⏳ Loading weather data …";
      try {
        await fetchWeatherNow();
      } catch (fetchErr) {
        document.getElementById("forecastRow").innerHTML =
          `<div class="forecast-loading">Error loading data – please refresh.</div>`;
        plotLoading.textContent = "Error loading.";
        return;
      }
    }
  }

  await Promise.all([
    loadSummary(),
    loadForecast(),
    loadHourlyPlot(currentPlotHours),
    loadSidebarWarnings(),
  ]);
}

init();

setInterval(() => {
  loadSummary();
  loadForecast();
  loadHourlyPlot(currentPlotHours);
}, 5 * 60 * 1000);
