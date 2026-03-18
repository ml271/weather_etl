/**
 * User Menu – shared widget for all pages.
 * Reads/writes localStorage("token").
 * Requires in the page: #userMenuBtn, #userPanel, and the inner IDs below.
 */

const _UMAPI = "/api";

async function initUserMenu() {
  const btn = document.getElementById("userMenuBtn");
  if (!btn) return;

  const token = localStorage.getItem("token");
  if (!token) {
    btn.title = "Anmelden";
    btn.addEventListener("click", () => {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = "login.html?next=" + next;
    });
    return;
  }

  try {
    const res = await fetch(`${_UMAPI}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error("invalid");
    const user = await res.json();

    // Mark as logged-in (green indicator)
    btn.classList.add("logged-in");
    btn.title = user.username;
    _populatePanel(user);
    btn.addEventListener("click", _togglePanel);

    // Load warnings in background
    _loadWarnings(token);
  } catch {
    localStorage.removeItem("token");
    btn.title = "Anmelden";
    btn.addEventListener("click", () => {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = "login.html?next=" + next;
    });
  }
}

function _populatePanel(user) {
  const el = (id) => document.getElementById(id);
  if (el("userPanelUsername")) el("userPanelUsername").textContent = user.username;
  if (el("userPanelEmail"))    el("userPanelEmail").textContent    = user.email;
}

async function _loadWarnings(token) {
  const container = document.getElementById("userPanelWarnings");
  if (!container) return;
  try {
    const res = await fetch(`${_UMAPI}/warnings/`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const warnings = await res.json();
    if (!warnings.length) {
      container.innerHTML = '<div style="font-size:11px;color:var(--text-dim);font-family:var(--font-mono);">Noch keine Warnungen.</div>';
    } else {
      container.innerHTML = "";
      warnings.forEach(w => {
        const div = document.createElement("div");
        div.style.cssText = "padding:.35rem .5rem;font-size:11px;cursor:pointer;border:1px solid var(--border);margin-bottom:.3rem;display:flex;align-items:center;gap:.4rem;";
        div.addEventListener("click", () => { window.location.href = "warnings.html?edit=" + encodeURIComponent(w.id); });
        div.addEventListener("mouseover", () => { div.style.borderColor = "var(--accent)"; });
        div.addEventListener("mouseout",  () => { div.style.borderColor = "var(--border)"; });

        const nameSpan = document.createElement("span");
        nameSpan.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
        nameSpan.textContent = w.name ?? "";

        const citySpan = document.createElement("span");
        citySpan.style.cssText = "font-size:10px;color:var(--text-dim);";
        citySpan.textContent = w.city ?? "";

        div.append(nameSpan, citySpan);
        container.appendChild(div);
      });
    }
  } catch { /* silent */ }
}

function _togglePanel() {
  const panel = document.getElementById("userPanel");
  if (!panel) return;
  const isOpen = panel.classList.toggle("open");
  if (isOpen) {
    setTimeout(() => {
      document.addEventListener("click", _closeOnOutside, { once: true });
    }, 0);
  }
}

function _closeOnOutside(e) {
  const panel = document.getElementById("userPanel");
  const btn   = document.getElementById("userMenuBtn");
  if (panel && !panel.contains(e.target) && btn && !btn.contains(e.target)) {
    panel.classList.remove("open");
  }
}

function userLogout() {
  localStorage.removeItem("token");
  window.location.reload();
}

document.addEventListener("DOMContentLoaded", initUserMenu);
