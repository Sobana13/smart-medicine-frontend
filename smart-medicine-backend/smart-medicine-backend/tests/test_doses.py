from datetime import timedelta

from extensions import db
from models import Dose, DoseStatusHistory
from services.reminder_service import mark_missed
from tests.conftest import make_dose, register
from utils import utcnow


def test_patient_reports_dose_taken(client):
    register(client)
    dose_id = make_dose("pat@example.com", minutes=-5)
    res = client.post(f"/api/doses/{dose_id}/status", json={"status": "taken"})
    body = res.get_json()
    assert res.status_code == 200 and body["status"] == "taken"
    assert body["reportedAt"] and body["statusSource"] == "patient_reported"
    assert body["verified"] is False  # patient-reported, never independently verified
    assert DoseStatusHistory.query.filter_by(dose_id=dose_id, new_status="taken").count() == 1


def test_invalid_status_and_unknown_dose(client):
    register(client)
    dose_id = make_dose("pat@example.com")
    assert client.post(f"/api/doses/{dose_id}/status", json={"status": "swallowed"}).status_code == 400
    assert client.post("/api/doses/99999/status", json={"status": "taken"}).status_code == 404


def test_cannot_update_another_patients_dose(client, app):
    register(client)
    dose_id = make_dose("pat@example.com")
    other = app.test_client()
    register(other, email="other@example.com")
    assert other.post(f"/api/doses/{dose_id}/status", json={"status": "taken"}).status_code == 404
    assert other.get(f"/api/doses/{dose_id}").status_code == 404
    assert db.session.get(Dose, dose_id).status == "pending"


def test_cannot_report_a_dose_far_in_the_future(client):
    register(client)
    dose_id = make_dose("pat@example.com", minutes=600)
    res = client.post(f"/api/doses/{dose_id}/status", json={"status": "taken"})
    assert res.status_code == 409 and res.get_json()["code"] == "too_early"


def test_missed_only_after_grace_period(client):
    register(client)
    recent = make_dose("pat@example.com", minutes=-10)   # inside the 30 minute grace period
    old = make_dose("pat@example.com", minutes=-45)      # grace period is over
    mark_missed(utcnow())
    assert db.session.get(Dose, recent).status == "pending"
    late = db.session.get(Dose, old)
    assert late.status == "missed" and late.status_source == "grace_period_elapsed"


def test_dashboard_uses_real_records(client):
    register(client)
    make_dose("pat@example.com", minutes=-20, status="taken")
    make_dose("pat@example.com", minutes=-40, status="missed")
    make_dose("pat@example.com", minutes=-5, status="pending")
    data = client.get("/api/dashboard").get_json()
    assert (data["scheduledToday"], data["taken"], data["missed"], data["pending"]) == (3, 1, 1, 1)
    assert data["adherence"]["todayPercent"] == 50
    assert data["next"]["overdue"] is True
    assert len(data["week"]) == 7 and data["demoMode"] is False


def test_schedule_creates_doses_without_duplicates(client):
    from tests.conftest import MED
    from utils import local_today
    register(client)
    client.post("/api/medicines", json={**MED, "start": local_today("Asia/Kolkata").isoformat()})
    tomorrow = (local_today("Asia/Kolkata") + timedelta(days=1)).isoformat()
    first = client.get(f"/api/schedule?date={tomorrow}").get_json()
    second = client.get(f"/api/schedule?date={tomorrow}").get_json()
    assert len(first) == 2 and [d["id"] for d in first] == [d["id"] for d in second]
    assert len({(d["medicineId"], d["time"]) for d in second}) == len(second)


def test_dose_history_hides_future_doses(client):
    register(client)
    make_dose("pat@example.com", minutes=-60, status="taken")
    make_dose("pat@example.com", minutes=300)
    history = client.get("/api/doses/history").get_json()
    assert len(history) == 1 and history[0]["status"] == "taken"
