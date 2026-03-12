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
    btn.addEventListener("click", () => { window.location.href = "login.html"; });
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
  } catch {
    localStorage.removeItem("token");
    btn.title = "Anmelden";
    btn.addEventListener("click", () => { window.location.href = "login.html"; });
  }
}

function _populatePanel(user) {
  const el = (id) => document.getElementById(id);
  if (el("userPanelUsername")) el("userPanelUsername").textContent = user.username;
  if (el("userPanelEmail"))    el("userPanelEmail").textContent    = user.email;
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
