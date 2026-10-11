"""Dashboard numbers, all calculated from real database rows."""
from datetime import timedelta
from flask import Blueprint, current_app, g, jsonify

from extensions import db
from models import Dose, DoseStatusHistory, Medicine
from security import login_required, target_patient
from services.reminder_service import ensure_doses
from utils import iso_local, local_today, utcnow

bp = Blueprint("dashboard", __name__, url_prefix="/api")


def _counts(patient_id, day):
    rows = Dose.query.filter_by(patient_id=patient_id, local_date=day).all()
    return {s: sum(1 for r in rows if r.status == s) for s in ("taken", "pending", "missed")}, rows


def _adherence(taken, missed):
    """Percent of RESOLVED doses (taken + missed) that the patient reported as taken. None when nothing is resolved yet."""
    return round(100 * taken / (taken + missed)) if taken + missed else None


@bp.get("/dashboard")
@login_required
def dashboard():
    patient = target_patient(g.user)
    tz, now = patient.timezone, utcnow()
    today = local_today(tz)
    ensure_doses(patient, today)
    counts, today_doses = _counts(patient.id, today)

    pending = sorted((d for d in today_doses if d.status == "pending"), key=lambda d: d.scheduled_for)
    upcoming = next((d for d in pending if d.scheduled_for >= now), None) or (pending[0] if pending else None)
    next_dose = None
    if upcoming:
        next_dose = {**upcoming.to_dict(tz), "overdue": upcoming.scheduled_for < now}

    week, w_taken, w_missed = [], 0, 0
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        c, _ = _counts(patient.id, day)
        week.append({"date": day.isoformat(), "label": day.strftime("%a"), **c})
        w_taken, w_missed = w_taken + c["taken"], w_missed + c["missed"]

    recent = (db.session.query(DoseStatusHistory, Dose, Medicine)
              .join(Dose, Dose.id == DoseStatusHistory.dose_id).join(Medicine, Medicine.id == Dose.medicine_id)
              .filter(Dose.patient_id == patient.id).order_by(DoseStatusHistory.changed_at.desc()).limit(10).all())

    active = Medicine.query.filter(Medicine.patient_id == patient.id, Medicine.start_date <= today,
                                   (Medicine.end_date.is_(None)) | (Medicine.end_date >= today)).count()
    return jsonify({
        "patientName": patient.name,
        "totalMedicines": active,
        "scheduledToday": len(today_doses),
        "taken": counts["taken"], "pending": counts["pending"], "missed": counts["missed"],
        "next": next_dose,
        "recentActivity": [{"doseId": d.id, "medicine": m.name, "oldStatus": h.old_status, "newStatus": h.new_status,
                            "source": h.source, "at": iso_local(h.changed_at, tz)} for h, d, m in recent],
        "adherence": {"todayPercent": _adherence(counts["taken"], counts["missed"]), "weekPercent": _adherence(w_taken, w_missed),
                      "basis": "taken / (taken + missed), based on patient-reported status"},
        "week": week,
        "graceMinutes": current_app.config["GRACE_PERIOD_MINUTES"],
        "demoMode": current_app.config["DEMO_MODE"],
    })
