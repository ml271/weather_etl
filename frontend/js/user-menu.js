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
    btn.title = "Sign in";
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
    btn.title = "Sign in";
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
      container.innerHTML = '<div style="font-size:11px;color:var(--text-dim);font-family:var(--font-mono);">No warnings yet.</div>';
    } else {
      container.innerHTML = warnings.map(w => `
        <div onclick="window.location.href='warnings.html?edit=${w.id}'"
             style="padding:.35rem .5rem;font-size:11px;cursor:pointer;border:1px solid var(--border);
                    margin-bottom:.3rem;display:flex;align-items:center;gap:.4rem;"
             onmouseover="this.style.borderColor='var(--accent)'"
             onmouseout="this.style.borderColor='var(--border)'">
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${w.name}</span>
          <span style="font-size:10px;color:var(--text-dim);">${w.city}</span>
        </div>`).join("");
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
