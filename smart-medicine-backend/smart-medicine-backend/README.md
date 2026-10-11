# Smart Medicine Reminder - Backend (Flask + SQLite + WhatsApp Cloud API)

This backend stores medicines, creates the daily dose schedule, tracks **patient-reported** dose status, lets linked
caregivers view data, and sends WhatsApp reminders through Meta's official WhatsApp Cloud API.

**Safety rules built in:** the app never suggests or changes a dosage (the patient types what the doctor prescribed);
"taken" means *patient-reported*, never verified; a dose becomes *missed* only after a grace period; real WhatsApp
messages are impossible while `DEMO_MODE=true` (the default).

## 1. Folder map

```
smart-medicine-backend/
  app.py                 creates the Flask app, registers routes, starts the scheduler
  config.py              reads settings from .env
  extensions.py          database / CORS / migrations objects
  models.py              database tables (users, medicines, doses, caregiver links, notifications...)
  security.py            "is the user logged in?" and "may they see this patient?" helpers
  utils.py               time zone + phone number helpers, ApiError
  run_scheduler.py       optional separate scheduler process (production)
  routes/                one file per feature (auth, medicines, doses, dashboard, caregivers, notifications, settings, whatsapp_webhook)
  services/              whatsapp_service.py (Meta API calls) and reminder_service.py (scheduler logic)
  tests/                 automated tests (never send real WhatsApp messages)
  .env.example           copy to .env and fill in
```

## 2. Setup on Windows 11 + VS Code

1. Install **Python 3.11+** from python.org (tick "Add python.exe to PATH"). Open the folder in VS Code.
2. Open a terminal in VS Code (Ctrl + the backtick key) and create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
   If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
   You should see `(venv)` at the start of the prompt. In VS Code choose it with `Ctrl+Shift+P` > *Python: Select Interpreter*.
3. Install packages: `pip install -r requirements.txt`
4. Copy the settings file: `copy .env.example .env`, then edit `.env`. For a first run you only need
   `SECRET_KEY` (generate with `python -c "import secrets; print(secrets.token_hex(32))"`). Keep `DEMO_MODE=true`.
5. Start the server: `python app.py` -> http://127.0.0.1:5000 . The SQLite file is created automatically in `instance/`.
6. Check it: open http://127.0.0.1:5000/api/auth/me - you should see `{"error": "Please log in to continue.", ...}`. That means it works.

## 3. Run the tests (no internet or WhatsApp needed)

```
pytest -v
```
Tests use an in-memory database and replace `requests.post`, so a real WhatsApp message can never be sent.

## 4. Connect your frontend

* Frontend (VS Code Live Server) runs at `http://127.0.0.1:5500`. That address is already in `CORS_ORIGINS`.
  CORS means the browser only allows pages from the listed origins to call the API. If your Live Server uses another
  port, add it to `CORS_ORIGINS` (comma separated). **Never use `*`** - the app refuses it in production.
* Use the same host name on both sides (`127.0.0.1` everywhere, or `localhost` everywhere) so the login cookie is sent.
* In the frontend `assets/js/api.js` set `USE_MOCK: false` and `API_BASE_URL: "http://127.0.0.1:5000"`.
  Every `fetch` must include `credentials: "include"` (the zip's `api.js` already does) so the session cookie is sent.
* Login uses a secure session cookie (HttpOnly, SameSite=Lax; Secure when `APP_ENV=production`).
  POST/PUT bodies must be JSON with `Content-Type: application/json` (this also blocks cross-site form attacks).

### Example fetch() calls
```js
const API = "http://127.0.0.1:5000/api";
async function call(path, method = "GET", body) {
  const res = await fetch(API + path, { method, credentials: "include",
    headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error);          // 400 validation, 401 login, 403 forbidden, 404, 409, 429, 503...
  return data;
}
// Login
await call("/auth/login", "POST", { email: "pat@example.com", password: "secret123" });
// Add a medicine (type exactly what the doctor prescribed)
await call("/medicines", "POST", { name: "Metformin", dosage: "500 mg tablet", instructions: "After food",
  start: "2026-10-11", end: "", frequency: "twice", times: ["08:00", "20:00"], doctor: "Dr. Rao", notes: "", remindersEnabled: true });
// Dashboard, schedule, dose status, test message
const dash = await call("/dashboard");
const doses = await call("/schedule?date=2026-10-11");
await call(`/doses/${doses[0].id}/status`, "POST", { status: "taken" });   // patient-reported
await call("/notifications/test", "POST", { target: "patient" });          // 503 until WhatsApp is configured
```
Caregivers add `?patientId=<id>` to GET requests (schedule, doses, dashboard, medicines, notifications).

## 5. API reference

Errors always look like `{"error": "message", "code": "machine_code", "details": {"field": "problem"}}`.

| Method + path | Who | Notes |
|---|---|---|
| POST `/api/auth/register` | anyone | `{name, email, phone (+countrycode), password (8+), role: patient\|caregiver}` -> 201 `{user}` (logged in) |
| POST `/api/auth/login` | anyone | `{email, password}` -> `{user}`. 5 wrong tries/15 min -> 429 |
| POST `/api/auth/logout`, GET `/api/auth/me` | any | `me` -> `{user:{id,name,email,phone,role,timezone}}` |
| GET/POST `/api/medicines`, GET/PUT/DELETE `/api/medicines/<id>` | patient (caregiver: GET only) | Medicine: `{id,name,dosage,instructions,start,end,frequency,times[],doctor,notes,remindersEnabled}`. `frequency`: once(1 time) / twice(2) / thrice(3) / custom(1-8) |
| GET `/api/schedule?date=YYYY-MM-DD` | patient/caregiver | List of doses (below). Today/future dates are generated; past dates show stored records only |
| GET `/api/doses` | patient/caregiver | filters `status, medicineId, from, to, limit, upcoming=1` |
| GET `/api/doses/history` | patient/caregiver | past doses, newest first, same filters |
| GET `/api/doses/<id>` | patient/caregiver | one dose |
| POST `/api/doses/<id>/status` | patient | `{status: pending\|taken\|missed}`. 409 `too_early` if more than `EARLY_REPORT_MINUTES` ahead |
| GET `/api/dashboard` | patient/caregiver | `{patientName,totalMedicines,scheduledToday,taken,pending,missed,next,recentActivity[],adherence{todayPercent,weekPercent},week[{date,label,taken,pending,missed}],graceMinutes,demoMode}` |
| GET/POST `/api/caregivers`, PUT/DELETE `/api/caregivers/<id>` | patient (caregiver: GET) | `{name,relationship,email?,whatsappNumber,consent:true,recipientOptIn,notifyMissed}`; consent is mandatory |
| GET `/api/notifications`, GET `/api/notifications/<id>` | patient/caregiver | `{id,type,recipientCategory,recipient(masked),doseId,createdAt,submitStatus,deliveryStatus,error,text,at}` |
| POST `/api/notifications/test` | patient | `{target:"patient"\|"caregiver", caregiverId?}`. 503 `demo_mode` / `whatsapp_not_configured`, 400 `no_opt_in`, 502 `send_failed`, 202 accepted |
| GET/PUT `/api/settings` | any / patient | `{patientName,timezone,patientWhatsapp,whatsappOptIn,remindersEnabled,caregiverAlertsEnabled,caregiverName,caregiverWhatsapp,graceMinutes,demoMode,whatsappConfigured}` (caregiver fields are read-only) |
| GET/POST `/api/whatsapp/webhook` | Meta only | verification + delivery status |

**Dose:** `{id, medicineId, name, dosage, instructions, date, time, scheduledAt, status, statusSource, reportedAt, verified:false, demo:false}`.
`statusSource` is `patient_reported` or `grace_period_elapsed` (system-marked after the grace period). `verified` is always `false`.
**Frontend field mapping:** the backend already uses the same names as the frontend prototype (`start`, `end`, `times`, `week`, `next`, `at`, `text`...).
Frontend phone fields must now be international format (`+919876543210`).

**Statuses:** `pending` = not confirmed yet (NOT the same as missed). `missed` = patient marked it, or no confirmation arrived within the grace period.
`submitStatus`: `submitted` only means Meta *accepted* the request; `deliveryStatus` (`sent/delivered/read/failed`) comes from the webhook.

## 6. WhatsApp Cloud API setup (do this only after everything works in demo mode)

1. Go to developers.facebook.com > *My Apps* > **Create App** > type *Business* > add the **WhatsApp** product.
2. In *WhatsApp > API Setup* copy the **Phone number ID** -> `WHATSAPP_PHONE_NUMBER_ID`. The page shows a temporary access token (24 h) for
   testing; for real use create a **System User** token in Business Settings (permission `whatsapp_business_messaging`) -> `WHATSAPP_ACCESS_TOKEN`.
3. Add your own number as a test recipient (API Setup > *To* > Manage phone number list). In the test setup you can only message numbers on that list.
4. *App settings > Basic*: copy **App secret** -> `WHATSAPP_APP_SECRET`.
5. In **WhatsApp Manager > Message templates** create two *Utility* templates in English and wait for approval
   (messages you start must use approved templates):
   * `medicine_reminder`, body: `Hello! 💊 It is time for your scheduled medicine.` / `Medicine: {{1}}` / `Prescribed dosage: {{2}}` / `Scheduled time: {{3}}` / `Please follow your doctor's instructions.`
   * `caregiver_missed_alert`, body: `⚠️ Medication Reminder Alert` / `Patient: {{1}}` / `Medicine: {{2}}` / `Scheduled time: {{3}}` / `This dose has not been confirmed as taken. Please check with the patient.`
   (Names can differ; set `WHATSAPP_TEMPLATE_REMINDER` / `WHATSAPP_TEMPLATE_CAREGIVER`.)
6. **Webhook:** Meta needs a public HTTPS address. For local testing install ngrok and run `ngrok http 5000`. In *WhatsApp > Configuration > Webhook*
   set Callback URL `https://<your-ngrok-id>.ngrok-free.app/api/whatsapp/webhook` and Verify token = the same random text as `WHATSAPP_VERIFY_TOKEN`,
   click *Verify and save*, then subscribe to the **messages** field. Signatures are checked with `WHATSAPP_APP_SECRET`.
7. In `.env` set `DEMO_MODE=false`, restart the server, log in as a patient, and use **Settings** to save your WhatsApp number with `whatsappOptIn: true`
   (`PUT /api/settings`), then call `POST /api/notifications/test`.
   Caregivers must be added with `consent: true` and `recipientOptIn: true` (the caregiver agreed to receive messages).

**Test locally before real notifications:** (1) run `pytest`; (2) keep `DEMO_MODE=true` and use the app - reminders and missed alerts are recorded in
`/api/notifications` with `submitStatus: "demo_not_sent"` and nothing is sent; (3) only then switch on real messages with your own number.

## 7. How the scheduler works (APScheduler)

Every minute `run_cycle()` (1) creates today's doses, (2) sends reminders for doses that are due, (3) marks doses *missed* once
`GRACE_PERIOD_MINUTES` (default 30) passed without confirmation, (4) alerts consenting caregivers. Duplicates are prevented by database rules:
doses are unique per medicine+time and every notification has a unique `event_key`, so even two scheduler copies cannot send a message twice.
Failed sends are recorded and **not** auto-retried later (avoids spamming); temporary errors (timeout, 429, 5xx) are retried 2 times immediately.

* **Development:** `python app.py` starts one scheduler (the Flask auto-reloader's extra process is handled). If you use `flask run`, set `SCHEDULER_ENABLED=false` and run `python run_scheduler.py` in a second terminal.
* **Production:** run web workers with `SCHEDULER_ENABLED=false` and run `python run_scheduler.py` as **one** separate process. With several web workers
  (e.g. gunicorn `-w 4`) each would start its own scheduler, wasting work and risking races. One dedicated worker is also easier to monitor and restart.

## 8. Database changes (migrations)

`python app.py` runs `db.create_all()`, which creates missing tables but **never changes existing ones**. When you change `models.py`:
```
set AUTO_CREATE_DB=false          (or put AUTO_CREATE_DB=false in .env)
flask --app app db init           (only the first time; creates the migrations folder)
flask --app app db migrate -m "describe the change"
flask --app app db upgrade
```
If you already have a development database made by `create_all`, delete `instance/medicine.db` once before starting with migrations (or `flask db stamp head` after the first migrate).
Timestamps are stored in UTC and converted to each patient's `timezone` (default from `TIMEZONE`) in API responses.

## 9. Security checklist

Passwords hashed (Werkzeug) - login throttling - session cookie HttpOnly/SameSite - JSON-only writes - CORS limited to your frontend - patients and caregivers
only reach their own/linked data (other patients' IDs return 404) - all input validated, SQL via SQLAlchemy - webhook signature (HMAC-SHA256) and verify token
checked - secrets only in `.env` (git-ignored) and never returned by any endpoint - phone numbers masked in logs/history, no medical data in server logs -
64 KB request limit - `Cache-Control: no-store`. **For deployment:** `APP_ENV=production`, HTTPS, a strong `SECRET_KEY`, exact `CORS_ORIGINS`; if the frontend is on a different site
set `SESSION_COOKIE_SAMESITE=None`. Known limits of this student project: caregiver emails are not verified (anyone who registers with the linked email becomes that caregiver),
the login throttle is in memory, and there is no password-reset email.
