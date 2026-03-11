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
const WEEKDAYS = ["SO","MO","DI","MI","DO","FR","SA"];

let currentPlotHours = 96;

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
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "short" });
}

// ─────────────────────────────────────────────────────
// Render: Summary
// ─────────────────────────────────────────────────────

function renderSummary(data) {
  document.getElementById("cityName").textContent = data.city || "—";
  document.getElementById("lastUpdated").textContent =
    data.last_updated
      ? "SYNC " + new Date(data.last_updated).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })
      : "KEIN SYNC";

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
  const fmt2 = d => d.toLocaleDateString("de-DE", { day: "2-digit", month: "short" });
  document.getElementById("forecastRange").textContent = `${fmt2(now)} – ${fmt2(end)}`;
}

// ─────────────────────────────────────────────────────
// Render: Alerts
// ─────────────────────────────────────────────────────

function renderAlerts(alerts) {
  const count   = alerts.length;
  const countEl = document.getElementById("alertCount");
  const listEl  = document.getElementById("alertsList");
  const banner  = document.getElementById("alertBanner");

  countEl.textContent = count;
  countEl.dataset.count = count;

  if (count === 0) {
    listEl.innerHTML = `<div class="no-alerts">Keine aktiven Warnungen ✓</div>`;
    banner.style.display = "none";
    return;
  }

  const dangers = alerts.filter(a => a.severity === "danger");
  if (dangers.length > 0) {
    banner.style.display = "block";
    banner.textContent = `⚡ ACHTUNG: ${dangers.map(d => d.alert_name).join(" · ")}`;
  } else {
    banner.style.display = "none";
  }

  listEl.innerHTML = alerts.map(a => `
    <div class="alert-chip ${a.severity}">
      <span class="chip-icon">${SEVERITY_ICONS[a.severity] ?? "⚡"}</span>
      <div class="chip-body">
        <span class="chip-name ${a.severity}">${a.alert_name.toUpperCase()}</span>
        <span class="chip-msg">${a.message}</span>
        <span class="chip-date">${a.forecast_date ? "📅 " + a.forecast_date : ""}</span>
      </div>
    </div>
  `).join("");
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
        <span class="f-weekday">${isToday ? "HEUTE" : weekday}</span>
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
  const dayNames = ["Sonntag","Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag"];
  title.textContent = `${dayNames[d.getDay()].toUpperCase()}  ·  ${d.toLocaleDateString("de-DE", { day:"2-digit", month:"long", year:"numeric" })}`;

  img.classList.remove("loaded");
  img.src = "";
  loading.style.display = "block";
  loading.textContent = "Lade Stundendaten...";
  modal.classList.add("open");
  document.body.style.overflow = "hidden";

  img.onload  = () => { loading.style.display = "none"; img.classList.add("loaded"); };
  img.onerror = () => { loading.textContent = "Keine Stundendaten für diesen Tag."; };
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
  loading.style.display = "block";

  const url = `${API}${apiPath(`/charts/hourly-plot?hours=${hours}`)}&_t=${Date.now()}`;

  img.onload = () => {
    loading.style.display = "none";
    img.classList.add("loaded");
  };
  img.onerror = () => {
    loading.textContent = "Keine Daten – ETL-Job ausführen!";
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
  const url = `${API}/weather/fetch-now?city=${encodeURIComponent(CITY)}&lat=${LAT}&lon=${LON}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error(`fetch-now → ${res.status}`);
  return true;
}

async function loadForecast() {
  try {
    const data = await apiFetch(apiPath("/forecast/daily?days=7"));
    renderForecast(data);
  } catch (e) {
    document.getElementById("forecastRow").innerHTML =
      `<div class="forecast-loading">Keine Daten – ETL-Job ausführen!</div>`;
  }
}

// ─────────────────────────────────────────────────────
// Init & Auto-Refresh
// ─────────────────────────────────────────────────────

async function init() {
  updateForecastRange();

  // If we have coords, check first whether data exists – if not, fetch before rendering
  if (CITY && LAT != null && LON != null) {
    try {
      await apiFetch(apiPath("/forecast/daily?days=1"));
    } catch (e) {
      if (e.message.includes("404")) {
        // Show loading state on both panels while fetching
        document.getElementById("forecastRow").innerHTML =
          `<div class="forecast-loading">⏳ Wetterdaten für ${CITY} werden geladen …</div>`;
        const plotLoading = document.getElementById("hourlyPlotLoading");
        plotLoading.style.display = "block";
        plotLoading.textContent = "⏳ Wetterdaten werden geladen …";
        try {
          await fetchWeatherNow();
        } catch (fetchErr) {
          document.getElementById("forecastRow").innerHTML =
            `<div class="forecast-loading">Fehler beim Laden – bitte Seite neu laden.</div>`;
          plotLoading.textContent = "Fehler beim Laden.";
          return;
        }
      }
    }
  }

  await Promise.all([
    loadSummary(),
    loadForecast(),
    loadHourlyPlot(currentPlotHours),
  ]);
}

init();

setInterval(() => {
  loadSummary();
  loadForecast();
  loadHourlyPlot(currentPlotHours);
}, 5 * 60 * 1000);
