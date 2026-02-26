/**
 * Weather Station Dashboard
 * Holt Daten von der FastAPI und rendert Charts + Alerts
 */

const API = "/api";   // Nginx proxy → backend:8000

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

let tempChart   = null;
let precipChart = null;
let currentChartMode = "daily";

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

function parseTime(str) {
  return str ? new Date(str) : null;
}

function fmtTime(dt) {
  if (!dt) return "—";
  return dt.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

// ─────────────────────────────────────────────────────
// Chart defaults
// ─────────────────────────────────────────────────────

Chart.defaults.color = "#4a6080";
Chart.defaults.font.family = "'Space Mono', monospace";
Chart.defaults.font.size = 10;

const chartBase = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: true, position: "top",
      labels: { boxWidth: 10, padding: 14, color: "#4a6080" }
    },
    tooltip: {
      backgroundColor: "#0d1520",
      borderColor: "rgba(74,158,255,0.3)",
      borderWidth: 1,
      titleColor: "#c8d8f0",
      bodyColor: "#4a6080",
      padding: 10,
    },
  },
  scales: {
    x: {
      grid: { color: "rgba(74,158,255,0.05)" },
      ticks: { color: "#2a3a52", maxRotation: 0 },
    },
    y: {
      grid: { color: "rgba(74,158,255,0.05)" },
      ticks: { color: "#2a3a52" },
    },
  },
};

// ─────────────────────────────────────────────────────
// Render: Summary / Hero card
// ─────────────────────────────────────────────────────

function renderSummary(data) {
  document.getElementById("cityName").textContent = data.city || "—";
  document.getElementById("lastUpdated").textContent =
    data.last_updated
      ? "SYNC " + new Date(data.last_updated).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })
      : "KEIN SYNC";

  const dot = document.getElementById("statusDot");
  dot.className = "status-dot " + (data.today ? "online" : "error");

  if (data.today) {
    const t = data.today;
    document.getElementById("heroIcon").textContent    = getIcon(t.weather_code);
    document.getElementById("heroTempMax").textContent = fmt(t.temperature_max, "°");
    document.getElementById("heroTempMin").textContent = fmt(t.temperature_min, "°");
    document.getElementById("heroDesc").textContent    = t.weather_description ?? "—";
    document.getElementById("heroRain").textContent    = fmt(t.precipitation_sum, " mm");
    document.getElementById("heroWind").textContent    = fmtInt(t.wind_speed_max, " km/h");
    document.getElementById("heroUV").textContent      = fmt(t.uv_index_max, "");
    document.getElementById("heroSnow").textContent    = fmt(t.snowfall_sum, " cm");

    // Sunrise / Sunset
    const rise = parseTime(t.sunrise);
    const set  = parseTime(t.sunset);
    document.getElementById("sunrise").textContent = fmtTime(rise);
    document.getElementById("sunset").textContent  = fmtTime(set);
    animateSunArc(rise, set);
  }

  renderAlerts(data.active_alerts ?? []);
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

  // Show danger banner at top
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
      <div class="forecast-day ${isToday ? "today" : ""}">
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
// Charts
// ─────────────────────────────────────────────────────

function buildTempChart(data) {
  const ctx = document.getElementById("tempChart").getContext("2d");
  if (tempChart) tempChart.destroy();

  tempChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Max °C",
          data: data.datasets.temperature_max,
          borderColor: "#ff9d4a",
          backgroundColor: "rgba(255,157,74,0.08)",
          tension: 0.4, fill: true, pointRadius: 4, pointBackgroundColor: "#ff9d4a",
        },
        {
          label: "Min °C",
          data: data.datasets.temperature_min,
          borderColor: "#4ad4ff",
          backgroundColor: "rgba(74,212,255,0.08)",
          tension: 0.4, fill: true, pointRadius: 4, pointBackgroundColor: "#4ad4ff",
        },
      ],
    },
    options: { ...chartBase },
  });
}

function buildHourlyChart(data) {
  const ctx = document.getElementById("tempChart").getContext("2d");
  if (tempChart) tempChart.destroy();

  tempChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
          label: "Temperatur °C",
          data: data.temperature,
          borderColor: "#ff9d4a",
          backgroundColor: "rgba(255,157,74,0.08)",
          tension: 0.4, fill: true, pointRadius: 2, pointBackgroundColor: "#ff9d4a",
        },
        {
          label: "Gefühlt °C",
          data: data.feels_like,
          borderColor: "#4a9eff",
          borderDash: [4, 4],
          tension: 0.4, fill: false, pointRadius: 0,
        },
      ],
    },
    options: { ...chartBase },
  });
}

function buildPrecipChart(data) {
  const ctx = document.getElementById("precipChart").getContext("2d");
  if (precipChart) precipChart.destroy();

  precipChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.labels,
      datasets: [{
        label: "Niederschlag mm",
        data: data.datasets?.precipitation ?? data.precipitation,
        backgroundColor: "rgba(74,158,255,0.4)",
        borderColor: "#4a9eff",
        borderWidth: 1,
        borderRadius: 2,
      }],
    },
    options: {
      ...chartBase,
      plugins: { ...chartBase.plugins, legend: { display: false } },
    },
  });
}

// ─────────────────────────────────────────────────────
// Sun Arc Animation
// ─────────────────────────────────────────────────────

function animateSunArc(rise, set) {
  if (!rise || !set) return;
  const now      = new Date();
  const total    = set - rise;
  const elapsed  = now - rise;
  const progress = Math.max(0, Math.min(1, elapsed / total));

  const arcLen = 283; // Approximate full arc length
  const offset = arcLen * (1 - progress);
  document.getElementById("arcProgress").style.strokeDashoffset = offset;

  // Sun dot position along arc
  const angle  = Math.PI * progress;   // 0 = left, π = right
  const cx     = 10 + 90 * (1 + Math.cos(Math.PI - angle));   // 10..190
  const cy     = 100 - 90 * Math.sin(angle);
  const dot    = document.getElementById("sunDot");
  dot.setAttribute("cx", cx);
  dot.setAttribute("cy", cy);
}

// ─────────────────────────────────────────────────────
// Chart toggle (7 Tage / 48h)
// ─────────────────────────────────────────────────────

window.switchChart = function(mode) {
  currentChartMode = mode;
  document.querySelectorAll(".toggle-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.chart === mode);
  });
  if (mode === "daily") {
    loadDailyCharts();
  } else {
    loadHourlyCharts();
  }
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
    const data = await apiFetch("/summary");
    renderSummary(data);
  } catch (e) {
    console.error("Summary failed:", e);
    document.getElementById("statusDot").className = "status-dot error";
    document.getElementById("lastUpdated").textContent = "OFFLINE";
    document.getElementById("heroDesc").textContent = "Backend nicht erreichbar – ETL-Job ausführen?";
  }
}

async function loadForecast() {
  try {
    const data = await apiFetch("/forecast/daily?days=7");
    renderForecast(data);
  } catch (e) {
    document.getElementById("forecastRow").innerHTML =
      `<div class="forecast-loading">Keine Daten – ETL-Job ausführen!</div>`;
  }
}

async function loadDailyCharts() {
  try {
    const data = await apiFetch("/stats/temperature");
    buildTempChart(data);
    buildPrecipChart(data);
  } catch (e) {
    console.warn("Daily chart data unavailable:", e);
  }
}

async function loadHourlyCharts() {
  try {
    const [hourly, dailyStats] = await Promise.all([
      apiFetch("/stats/hourly-temp?hours=48"),
      apiFetch("/stats/temperature"),
    ]);
    buildHourlyChart(hourly);
    buildPrecipChart(dailyStats);
  } catch (e) {
    console.warn("Hourly chart data unavailable:", e);
  }
}

// ─────────────────────────────────────────────────────
// Init & Auto-Refresh
// ─────────────────────────────────────────────────────

async function init() {
  await Promise.all([
    loadSummary(),
    loadForecast(),
    loadDailyCharts(),
  ]);
}

init();

// Alle 5 Minuten neu laden
setInterval(() => {
  loadSummary();
  if (currentChartMode === "daily") loadDailyCharts();
  else loadHourlyCharts();
}, 5 * 60 * 1000);
