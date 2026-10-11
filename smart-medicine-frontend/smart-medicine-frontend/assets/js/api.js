"use strict";
/* API service. Set USE_MOCK=false and API_BASE_URL to your Flask server to go live.
   Never put Meta/WhatsApp tokens here: the Flask backend must hold them. */
const CONFIG = { API_BASE_URL: "http://127.0.0.1:5000", USE_MOCK: true };

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
const pad = n => String(n).padStart(2, "0");
const toDateStr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ---------- Mock backend (demonstration data, kept in sessionStorage only) ---------- */
const MockDB = {
  key: "smd_demo_db",
  load() {
    try { const raw = sessionStorage.getItem(this.key); if (raw) return JSON.parse(raw); } catch (e) {}
    const d = this.seed(); this.save(d); return d;
  },
  save(d) { try { sessionStorage.setItem(this.key, JSON.stringify(d)); } catch (e) {} },
  seed() {
    const start = toDateStr(new Date(Date.now() - 14 * 864e5));
    return {
      nextId: 4,
      medicines: [
        { id: 1, name: "Metformin", dosage: "500 mg tablet", instructions: "Take after breakfast and dinner", start, end: "", frequency: "twice", times: ["08:00", "20:00"], doctor: "Dr. Rao", notes: "Sample entry" },
        { id: 2, name: "Amlodipine", dosage: "5 mg tablet", instructions: "Take once in the morning", start, end: "", frequency: "once", times: ["09:00"], doctor: "Dr. Rao", notes: "Sample entry" },
        { id: 3, name: "Vitamin D3", dosage: "1 capsule", instructions: "Take with lunch", start, end: "", frequency: "once", times: ["13:00"], doctor: "", notes: "Sample entry" }
      ],
      doses: {},
      notifications: [{ id: 1, channel: "app", text: "Demonstration data loaded. No WhatsApp messages have been sent.", at: new Date().toISOString(), status: "demo" }],
      settings: { patientName: "Demo Patient", patientWhatsapp: "", caregiverName: "", caregiverWhatsapp: "", remindersEnabled: true, caregiverAlertsEnabled: true }
    };
  }
};

/* Past days without a stored record get labelled demo statuses; today stays "pending" until reported. */
function buildDoses(db, date) {
  const today = toDateStr(new Date()), out = [];
  db.medicines.forEach(m => {
    if (date < m.start || (m.end && date > m.end)) return;
    m.times.forEach(t => {
      const id = `${m.id}_${date}_${t.replace(":", "")}`, rec = db.doses[id];
      let status = "pending", reportedAt = null, demo = false;
      if (rec) { status = rec.status; reportedAt = rec.at; }
      else if (date < today) {
        const h = (parseInt(date.replace(/-/g, ""), 10) + m.id * 7 + parseInt(t, 10) * 3) % 10;
        status = h === 0 ? "missed" : "taken"; demo = true;
      }
      out.push({ id, medicineId: m.id, name: m.name, dosage: m.dosage, instructions: m.instructions, date, time: t, status, reportedAt, demo });
    });
  });
  return out.sort((a, b) => a.time.localeCompare(b.time));
}

function mock(path, opt) {
  const db = MockDB.load(), method = (opt.method || "GET").toUpperCase(), body = opt.body || {};
  const url = new URL(path, "http://x"), p = url.pathname; let m;
  if (p === "/api/medicines" && method === "GET") return db.medicines;
  if (p === "/api/medicines" && method === "POST") { const med = { ...body, id: db.nextId++ }; db.medicines.push(med); MockDB.save(db); return med; }
  if ((m = p.match(/^\/api\/medicines\/(\d+)$/))) {
    const id = +m[1], i = db.medicines.findIndex(x => x.id === id);
    if (i < 0) throw new ApiError("Medicine not found.", 404);
    if (method === "PUT") { db.medicines[i] = { ...body, id }; MockDB.save(db); return db.medicines[i]; }
    if (method === "DELETE") { db.medicines.splice(i, 1); MockDB.save(db); return { deleted: id }; }
  }
  if (p === "/api/schedule") return buildDoses(db, url.searchParams.get("date") || toDateStr(new Date()));
  if ((m = p.match(/^\/api\/doses\/([^/]+)\/status$/)) && method === "POST") {
    const id = decodeURIComponent(m[1]);
    if (!["taken", "missed", "pending"].includes(body.status)) throw new ApiError("Invalid status.", 400);
    const dose = buildDoses(db, id.split("_")[1]).find(d => d.id === id);
    if (!dose) throw new ApiError("Dose not found.", 404);
    db.doses[id] = { status: body.status, at: new Date().toISOString() };
    db.notifications.unshift({ id: Date.now(), channel: "app", text: `${dose.name} (${dose.time}) reported as ${body.status} by patient.`, at: new Date().toISOString(), status: "demo" });
    MockDB.save(db); return { ...dose, status: body.status };
  }
  if (p === "/api/dashboard") {
    const now = new Date(), nowHM = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    const ds = buildDoses(db, toDateStr(now)), count = (list, s) => list.filter(d => d.status === s).length;
    const pend = ds.filter(d => d.status === "pending"), next = pend.find(d => d.time >= nowHM) || pend[0] || null;
    const week = [];
    for (let i = 6; i >= 0; i--) {
      const dt = new Date(Date.now() - i * 864e5), x = buildDoses(db, toDateStr(dt));
      week.push({ date: toDateStr(dt), label: dt.toLocaleDateString(undefined, { weekday: "short" }), taken: count(x, "taken"), pending: count(x, "pending"), missed: count(x, "missed") });
    }
    return { totalMedicines: db.medicines.length, scheduledToday: ds.length, taken: count(ds, "taken"), pending: count(ds, "pending"), missed: count(ds, "missed"), next: next && { ...next, overdue: next.time < nowHM }, week, demo: true };
  }
  if (p === "/api/notifications" && method === "GET") return db.notifications;
  if (p === "/api/notifications/test" && method === "POST")
    throw new ApiError("The WhatsApp service is not configured, so no message was sent. Connect the Flask backend and the Meta WhatsApp Cloud API to enable test messages.", 503);
  if (p === "/api/settings") { if (method === "PUT") { db.settings = { ...db.settings, ...body }; MockDB.save(db); } return db.settings; }
  throw new ApiError("Unknown endpoint.", 404);
}

/* ---------- Request wrapper ---------- */
async function request(path, opt = {}) {
  if (CONFIG.USE_MOCK) { await sleep(300); return structuredClone(mock(path, opt)); }
  let res;
  try {
    res = await fetch(CONFIG.API_BASE_URL + path, {
      method: opt.method || "GET", headers: { "Content-Type": "application/json" },
      body: opt.body ? JSON.stringify(opt.body) : undefined
    });
  } catch (e) { throw new ApiError("Cannot reach the server. Check that the Flask backend is running and the API base URL is correct.", 0); }
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
    throw new ApiError(msg, res.status);
  }
  return res.status === 204 ? null : res.json();
}

const Api = {
  getMedicines: () => request("/api/medicines"),
  addMedicine: body => request("/api/medicines", { method: "POST", body }),
  updateMedicine: (id, body) => request(`/api/medicines/${id}`, { method: "PUT", body }),
  deleteMedicine: id => request(`/api/medicines/${id}`, { method: "DELETE" }),
  getSchedule: date => request(`/api/schedule?date=${encodeURIComponent(date)}`),
  setDoseStatus: (id, status) => request(`/api/doses/${encodeURIComponent(id)}/status`, { method: "POST", body: { status } }),
  getDashboard: () => request("/api/dashboard"),
  getNotifications: () => request("/api/notifications"),
  sendTestNotification: body => request("/api/notifications/test", { method: "POST", body }),
  getSettings: () => request("/api/settings"),
  updateSettings: body => request("/api/settings", { method: "PUT", body })
};
