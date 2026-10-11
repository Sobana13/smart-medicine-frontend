"use strict";
/* Shared helpers + app shell (sidebar, topbar, toasts, dialogs). Load after api.js. */

  
const NAV = [
    ["dashboard", "Dashboard", "fa-solid fa-gauge-high"],
    ["medicines", "Medicines", "fa-solid fa-pills"],
    ["schedule", "Schedule", "fa-solid fa-calendar-check"],
    ["caregiver", "Caregiver view", "fa-solid fa-user-nurse"],
    ["whatsapp-alerts", "WhatsApp alerts", "fa-brands fa-whatsapp"],
    ["history", "History and reports", "fa-solid fa-chart-column"],
    ["profile", "Profile and settings", "fa-solid fa-gear"]
];

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = t => { const [h, m] = t.split(":").map(Number); return `${h % 12 || 12}:${pad(m)} ${h < 12 ? "AM" : "PM"}`; };

/* Session holds only name + role (never passwords). Demo only: not real authentication. */
const getSession = () => { try { return JSON.parse(sessionStorage.getItem("smd_session")); } catch (e) { return null; } };
const setSession = s => sessionStorage.setItem("smd_session", JSON.stringify(s));
function logout() { sessionStorage.removeItem("smd_session"); location.href = "login.html"; }

/* Non-sensitive display preference (text size) */
const getPrefs = () => { try { return JSON.parse(localStorage.getItem("smd_prefs")) || {}; } catch (e) { return {}; } };
function setLargeText(on) {
  document.documentElement.classList.toggle("large-text", on);
  try { localStorage.setItem("smd_prefs", JSON.stringify({ ...getPrefs(), largeText: on })); } catch (e) {}
}

function statusBadge(status, demo) {
  const map = { taken: ["b-taken", "fa-circle-check", "Reported taken"], pending: ["b-pending", "fa-clock", "Pending"], missed: ["b-missed", "fa-circle-xmark", "Marked missed"] };
  const [cls, icon, label] = map[status] || map.pending;
  return `<span class="badge ${cls}"><i class="fa-solid ${icon}" aria-hidden="true"></i>${label}</span>${demo ? ' <span class="badge b-demo">Demo data</span>' : ""}`;
}

function toast(message, type = "info") {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; box.setAttribute("aria-live", "polite"); document.body.append(box); }
  const t = document.createElement("div"); t.className = `toast ${type}`; t.setAttribute("role", type === "error" ? "alert" : "status");
  t.innerHTML = `<i class="fa-solid ${type === "error" ? "fa-triangle-exclamation" : type === "success" ? "fa-circle-check" : "fa-circle-info"}" aria-hidden="true"></i><span>${esc(message)}</span>`;
  box.append(t); setTimeout(() => t.remove(), type === "error" ? 8000 : 4500);
}

function confirmDialog({ title, message, confirmText = "Confirm", danger = false }) {
  return new Promise(resolve => {
    const d = document.createElement("dialog"); d.className = "modal";
    d.innerHTML = `<h2>${esc(title)}</h2><p>${esc(message)}</p><div class="row end"><button type="button" class="btn btn-ghost" value="no">Cancel</button><button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" value="yes">${esc(confirmText)}</button></div>`;
    d.addEventListener("click", e => { const b = e.target.closest("button"); if (b) d.close(b.value); });
    d.addEventListener("close", () => { resolve(d.returnValue === "yes"); d.remove(); });
    document.body.append(d); d.showModal();
  });
}

function buildShell() {
  const page = document.body.dataset.page, main = document.getElementById("main"), sess = getSession();
  const shell = document.createElement("div"); shell.className = "shell";
  shell.innerHTML = `
  <aside class="sidebar" id="sidebar" aria-label="Main navigation">
    <a class="brand" href="dashboard.html"><span class="brand-mark"><i class="fa-solid fa-heart-pulse" aria-hidden="true"></i></span>MediRemind</a>
    <nav class="nav">${NAV.map(([k, label, icon]) => `<a href="${k}.html" ${k === page ? 'aria-current="page"' : ""}><i class="${icon}" aria-hidden="true"></i>${label}</a>`).join("")}</nav>
    <div class="side-foot"><div>${esc(sess?.name || "Guest")}<br><span class="muted">${sess?.role === "caregiver" ? "Caregiver" : "Patient"} (demo sign-in)</span></div>
      <button class="btn btn-ghost btn-sm" id="logoutBtn" style="margin-top:.7rem"><i class="fa-solid fa-right-from-bracket" aria-hidden="true"></i>Log out</button></div>
  </aside>
  <div class="content">
    <header class="topbar">
      <button class="btn btn-ghost btn-sm" id="menuBtn" aria-label="Open menu" aria-expanded="false" aria-controls="sidebar"><i class="fa-solid fa-bars"></i></button>
      <strong class="grow">${esc(NAV.find(n => n[0] === page)?.[1] || "")}</strong>
      <button class="btn btn-ghost btn-sm" id="textBtn" aria-pressed="false" title="Toggle larger text"><i class="fa-solid fa-text-height" aria-hidden="true"></i>Larger text</button>
    </header>
    <div class="demo-banner" role="note"><i class="fa-solid fa-flask" aria-hidden="true"></i> Demo mode: sample data is stored in this browser tab only. Not connected to a backend.</div>
  </div>`;
  document.body.prepend(shell);
  shell.querySelector(".content").append(main);
  const side = shell.querySelector("#sidebar"), menu = shell.querySelector("#menuBtn"), textBtn = shell.querySelector("#textBtn");
  menu.onclick = () => { const o = side.classList.toggle("open"); menu.setAttribute("aria-expanded", o); };
  side.addEventListener("click", e => { if (e.target.closest("a")) side.classList.remove("open"); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") side.classList.remove("open"); });
  shell.querySelector("#logoutBtn").onclick = logout;
  textBtn.setAttribute("aria-pressed", !!getPrefs().largeText);
  textBtn.onclick = () => { const on = !document.documentElement.classList.contains("large-text"); setLargeText(on); textBtn.setAttribute("aria-pressed", on); };
}

document.addEventListener("DOMContentLoaded", () => {
  if (getPrefs().largeText) document.documentElement.classList.add("large-text");
  if (document.body.dataset.page && document.getElementById("main")) {
    if (!getSession()) { location.replace("login.html"); return; }
    buildShell();
  }
});
