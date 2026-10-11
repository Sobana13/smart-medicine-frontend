"use strict";
/* Dashboard page: loads stats, today's schedule and notifications through Api (see api.js). */
async function loadDashboard() {
  const stats = document.getElementById("stats");
  try {
    const [s, sched, notes] = await Promise.all([Api.getDashboard(), Api.getSchedule(toDateStr(new Date())), Api.getNotifications()]);
    renderStats(s); renderNext(s.next); renderChart(s.week); renderSchedule(sched); renderNotes(notes);
  } catch (e) {
    stats.innerHTML = `<div class="error-box" style="grid-column:1/-1" role="alert"><p><i class="fa-solid fa-triangle-exclamation"></i> ${esc(e.message)}</p><button class="btn btn-ghost btn-sm" id="retry">Try again</button></div>`;
    document.getElementById("retry").onclick = () => { stats.innerHTML = '<div class="skeleton"></div>'; loadDashboard(); };
  }
}

function renderStats(s) {
  const cards = [
    ["medicines.html", "fa-pills", "i-teal", s.totalMedicines, "Total medicines"],
    ["schedule.html", "fa-calendar-day", "i-blue", s.scheduledToday, "Scheduled today"],
    ["schedule.html", "fa-circle-check", "i-ok", s.taken, "Reported taken"],
    ["schedule.html", "fa-clock", "i-amber", s.pending, "Pending"],
    ["history.html", "fa-circle-xmark", "i-red", s.missed, "Marked missed"]
  ];
  document.getElementById("stats").innerHTML = cards.map(([href, ic, tone, n, label]) =>
    `<a class="stat" href="${href}"><div class="ico ${tone}"><i class="fa-solid ${ic}" aria-hidden="true"></i></div><b>${n}</b><span>${label}</span></a>`).join("");
}

function renderNext(n) {
  const box = document.getElementById("next");
  if (!n) { box.innerHTML = `<h2>Next reminder</h2><p class="big" style="font-size:1.4rem">All done for today</p><p>No pending doses are left on today's schedule.</p>`; return; }
  box.innerHTML = `<h2>${n.overdue ? "Overdue reminder" : "Next reminder"}</h2>
    <div class="big">${fmtTime(n.time)}</div>
    <p style="margin:.5rem 0 1rem"><strong>${esc(n.name)}</strong>, prescribed dosage: ${esc(n.dosage)}<br>${esc(n.instructions || "Follow your doctor's instructions.")}</p>
    <div class="row"><button class="btn btn-primary" data-dose="${esc(n.id)}" data-status="taken"><i class="fa-solid fa-check"></i>Mark as taken</button></div>`;
}

function renderChart(week) {
  const max = Math.max(1, ...week.map(d => d.taken + d.pending + d.missed));
  document.getElementById("chart").innerHTML = `<div class="bars">${week.map(d => {
    const h = k => (d[k] / max * 100).toFixed(1);
    return `<div class="bar-col" role="img" aria-label="${d.label}: ${d.taken} reported taken, ${d.pending} pending, ${d.missed} marked missed">
      <div class="bar"><i class="s-taken" style="height:${h("taken")}%"></i><i class="s-pending" style="height:${h("pending")}%"></i><i class="s-missed" style="height:${h("missed")}%"></i></div><small>${d.label}</small></div>`;
  }).join("")}</div>
  <div class="legend"><span style="--c:var(--green)">Reported taken</span><span style="--c:#e0a800">Pending</span><span style="--c:var(--red)">Marked missed</span></div>
  <p class="muted" style="font-size:.85rem;margin-top:.6rem">Days before today use demonstration data.</p>`;
}

function renderSchedule(list) {
  const box = document.getElementById("sched");
  if (!list.length) { box.innerHTML = `<div class="empty"><p><strong>No medicines scheduled today.</strong></p><a class="btn btn-primary btn-sm" href="medicines.html">Add a medicine</a></div>`; return; }
  box.innerHTML = `<ul class="list">${list.map(d => `<li>
    <span class="time">${fmtTime(d.time)}</span>
    <div class="grow"><strong>${esc(d.name)}</strong><br><span class="muted">Prescribed dosage: ${esc(d.dosage)}</span></div>
    ${statusBadge(d.status)}
    ${d.status === "pending" ? `<button class="btn btn-ghost btn-sm" data-dose="${esc(d.id)}" data-status="taken">Mark as taken</button><button class="btn btn-ghost btn-sm" data-dose="${esc(d.id)}" data-status="missed">Mark as missed</button>` : ""}
  </li>`).join("")}</ul>`;
}

function renderNotes(list) {
  document.getElementById("notes").innerHTML = list.length
    ? list.slice(0, 5).map(n => `<li><i class="fa-solid fa-bell i-teal" style="padding:.6rem;border-radius:10px" aria-hidden="true"></i><div class="grow">${esc(n.text)}<br><small class="muted">${new Date(n.at).toLocaleString()}</small></div></li>`).join("")
    : `<li class="muted">No notifications yet.</li>`;
}

/* Patient-reported status: updates the UI right after the API call succeeds. */
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-dose]");
  if (!btn) return;
  btn.disabled = true;
  try {
    await Api.setDoseStatus(btn.dataset.dose, btn.dataset.status);
    toast(btn.dataset.status === "taken" ? "Saved as reported taken." : "Saved as marked missed.", "success");
    await loadDashboard();
  } catch (err) { toast(err.message, "error"); btn.disabled = false; }
});

document.addEventListener("DOMContentLoaded", () => {
  const s = getSession(); if (!s) return;
  document.getElementById("greet").textContent = `Welcome, ${s.name}`;
  document.getElementById("today").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  loadDashboard();
});
