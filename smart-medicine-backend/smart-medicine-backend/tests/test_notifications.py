"""WhatsApp tests. requests.post is always replaced by a fake, so NO real message can be sent."""
import hashlib
import hmac
import json

import pytest

from extensions import db
from models import CaregiverLink, Dose, NotificationRecord, User
from services import whatsapp_service as wa
from services.reminder_service import dispatch, mark_missed, notify_caregivers, send_due_reminders
from tests.conftest import make_dose, register
from utils import utcnow


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body or {"messages": [{"id": "wamid.TEST1"}]}

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def never_hit_the_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("A real HTTP request was attempted!")
    monkeypatch.setattr(wa.requests, "post", blocked)
    monkeypatch.setattr(wa, "_sleep", lambda s: None)


def configure(app):
    app.config.update(WHATSAPP_ACCESS_TOKEN="SECRET-TOKEN", WHATSAPP_PHONE_NUMBER_ID="12345", WHATSAPP_API_VERSION="v21.0")


def opt_in(client, number="+919876543210"):
    return client.put("/api/settings", json={"patientWhatsapp": number, "whatsappOptIn": True})


# ---------- test endpoint ----------
def test_test_endpoint_in_demo_mode_sends_nothing(client, app):
    app.config["DEMO_MODE"] = True
    register(client)
    res = client.post("/api/notifications/test", json={"target": "patient"})
    assert res.status_code == 503 and res.get_json()["code"] == "demo_mode"


def test_test_endpoint_without_credentials(client):
    register(client)
    res = client.post("/api/notifications/test", json={"target": "patient"})
    assert res.status_code == 503 and res.get_json()["code"] == "whatsapp_not_configured"
    assert NotificationRecord.query.count() == 0


def test_test_endpoint_requires_opt_in(client, app):
    configure(app)
    register(client)
    assert client.post("/api/notifications/test", json={"target": "patient"}).status_code == 400


def test_test_endpoint_sends_when_configured(client, app, monkeypatch):
    configure(app)
    register(client)
    opt_in(client)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers, timeout))
        return FakeResponse()
    monkeypatch.setattr(wa.requests, "post", fake_post)

    res = client.post("/api/notifications/test", json={"target": "patient"})
    assert res.status_code == 202 and len(calls) == 1
    assert "SECRET-TOKEN" not in res.get_data(as_text=True)          # secrets never leave the server
    assert calls[0][1]["to"] == "919876543210" and calls[0][3] == wa.TIMEOUT_SECONDS
    row = NotificationRecord.query.one()
    assert row.submit_status == "submitted" and row.delivery_status is None  # accepted != delivered
    assert row.recipient_masked.endswith("3210") and "9876" not in row.recipient_masked


def test_api_failure_is_reported_not_hidden(client, app, monkeypatch):
    configure(app)
    register(client)
    opt_in(client)
    monkeypatch.setattr(wa.requests, "post", lambda *a, **k: FakeResponse(400, {"error": {"code": 132001, "message": "Template missing"}}))
    res = client.post("/api/notifications/test", json={"target": "patient"})
    assert res.status_code == 502 and "132001" in res.get_json()["error"]


def test_temporary_errors_are_retried(app, monkeypatch):
    configure(app)
    answers = [FakeResponse(500, {"error": {"code": 2, "message": "temp"}}), FakeResponse(429, {}), FakeResponse()]
    monkeypatch.setattr(wa.requests, "post", lambda *a, **k: answers.pop(0))
    result = wa.send_template("+919876543210", "medicine_reminder", ["A", "B", "C"])
    assert result["status"] == "submitted" and not answers


def test_invalid_phone_number_is_rejected(app):
    assert wa.send_template("98765", "t", ["a"])["status"] == "invalid_number"


# ---------- scheduler behaviour ----------
def test_same_event_is_never_sent_twice(client):
    register(client)
    uid = User.query.first().id
    sent = []
    fn = lambda: sent.append(1) or {"status": "submitted", "message_id": "m1", "error": None}
    first = dispatch(uid, None, "reminder", "patient", "+919876543210", "reminder:1:patient", fn)
    again = dispatch(uid, None, "reminder", "patient", "+919876543210", "reminder:1:patient", fn)
    assert first is not None and again is None and len(sent) == 1


def _patient_with_whatsapp(client):
    register(client)
    user = User.query.filter_by(email="pat@example.com").first()
    user.whatsapp_number, user.whatsapp_opt_in = "+919876543210", True
    db.session.commit()
    return user


def test_reminder_is_recorded_once_and_not_sent_in_demo_mode(client, app):
    app.config["DEMO_MODE"] = True
    _patient_with_whatsapp(client)
    make_dose("pat@example.com", minutes=-1)
    for _ in range(3):
        send_due_reminders(utcnow())
    rows = NotificationRecord.query.all()
    assert len(rows) == 1 and rows[0].submit_status == "demo_not_sent"


def test_reminders_respect_preferences(client, app):
    app.config["DEMO_MODE"] = True
    _patient_with_whatsapp(client)
    client.put("/api/settings", json={"remindersEnabled": False})
    make_dose("pat@example.com", minutes=-1)
    send_due_reminders(utcnow())
    assert NotificationRecord.query.count() == 0


def test_caregiver_alert_needs_consent_and_is_sent_once(client, app):
    app.config["DEMO_MODE"] = True
    user = _patient_with_whatsapp(client)
    dose_id = make_dose("pat@example.com", minutes=-45)
    link = CaregiverLink(patient_id=user.id, name="Asha", whatsapp_number="+919811111111", consent_given=False, recipient_opt_in=True)
    db.session.add(link)
    db.session.commit()
    notify_caregivers(mark_missed(utcnow()), utcnow())
    assert NotificationRecord.query.count() == 0           # no consent -> no alert
    link.consent_given = True
    db.session.commit()
    missed = [db.session.get(Dose, dose_id)]
    for _ in range(2):
        notify_caregivers(missed, utcnow())
    assert NotificationRecord.query.filter_by(type="caregiver_missed").count() == 1


# ---------- webhook ----------
def _signed(client, payload, secret="appsecret", good=True):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if good else "0" * 64
    return client.post("/api/whatsapp/webhook", data=body, headers={"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"})


def _status(message_id, status):
    return {"entry": [{"changes": [{"value": {"statuses": [{"id": message_id, "status": status}]}}]}]}


def test_webhook_verification(client, app):
    app.config["WHATSAPP_VERIFY_TOKEN"] = "my-verify-token"
    ok = client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=my-verify-token&hub.challenge=987")
    assert ok.status_code == 200 and ok.get_data(as_text=True) == "987"
    assert client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=987").status_code == 403


def test_webhook_verification_fails_when_token_not_configured(client):
    assert client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=&hub.challenge=1").status_code == 403


def test_webhook_rejects_bad_signature(client, app):
    app.config["WHATSAPP_APP_SECRET"] = "appsecret"
    assert _signed(client, _status("wamid.A", "delivered"), good=False).status_code == 403


def test_webhook_updates_delivery_status_idempotently(client, app):
    app.config["WHATSAPP_APP_SECRET"] = "appsecret"
    register(client)
    user = User.query.first()
    db.session.add(NotificationRecord(patient_id=user.id, type="test", recipient_category="patient", recipient_masked="*****3210",
                                      wa_message_id="wamid.A", submit_status="submitted"))
    db.session.commit()
    for status in ("delivered", "delivered", "read", "delivered"):  # repeated and out-of-order updates
        assert _signed(client, _status("wamid.A", status)).status_code == 200
    assert NotificationRecord.query.one().delivery_status == "read"
