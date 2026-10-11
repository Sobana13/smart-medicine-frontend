"""Schedule + dose tracking. Dose status is PATIENT-REPORTED; the app cannot verify that medicine was consumed."""
from datetime import date, datetime, timedelta
from flask import Blueprint, current_app, g, jsonify, request

from extensions import db
from models import DOSE_STATUSES, Dose, DoseStatusHistory, Medicine
from security import json_body, login_required, patient_only, target_patient
from services.reminder_service import ensure_doses
from utils import ApiError, local_today, utcnow

bp = Blueprint("doses", __name__, url_prefix="/api")


def _parse_date(text, field):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be a date like 2026-10-11.", 400, "validation_error", {field: "Use YYYY-MM-DD."})


def _limit():
    return max(1, min(request.args.get("limit", 100, type=int), 500))


def _filtered(query):
    """Shared filters for /doses and /doses/history: ?status= ?medicineId= ?from= ?to="""
    status = request.args.get("status")
    if status:
        if status not in DOSE_STATUSES:
            raise ApiError("status must be pending, taken or missed.", 400, "validation_error")
        query = query.filter(Dose.status == status)
    if request.args.get("medicineId", type=int):
        query = query.filter(Dose.medicine_id == request.args.get("medicineId", type=int))
    if request.args.get("from"):
        query = query.filter(Dose.local_date >= _parse_date(request.args["from"], "from"))
    if request.args.get("to"):
        query = query.filter(Dose.local_date <= _parse_date(request.args["to"], "to"))
    return query


@bp.get("/schedule")
@login_required
def schedule():
    patient = target_patient(g.user)
    today = local_today(patient.timezone)
    day = _parse_date(request.args["date"], "date") if request.args.get("date") else today
    if today <= day <= today + timedelta(days=30):
        ensure_doses(patient, day)  # only today/future days are generated; past days show stored records only
    doses = Dose.query.filter_by(patient_id=patient.id, local_date=day).order_by(Dose.scheduled_for).all()
    return jsonify([d.to_dict(patient.timezone) for d in doses])


@bp.get("/doses")
@login_required
def list_doses():
    patient = target_patient(g.user)
    query = Dose.query.filter_by(patient_id=patient.id)
    if request.args.get("upcoming"):  # ?upcoming=1 -> pending doses from now on (today + tomorrow)
        today = local_today(patient.timezone)
        for offset in (0, 1):
            ensure_doses(patient, today + timedelta(days=offset))
        floor = utcnow() - timedelta(minutes=current_app.config["GRACE_PERIOD_MINUTES"])
        query = query.filter(Dose.status == "pending", Dose.scheduled_for >= floor)
    doses = _filtered(query).order_by(Dose.scheduled_for).limit(_limit()).all()
    return jsonify([d.to_dict(patient.timezone) for d in doses])


@bp.get("/doses/history")
@login_required
def dose_history():
    """Past doses (newest first). Pending doses whose time has not come yet are left out."""
    patient = target_patient(g.user)
    query = Dose.query.filter(Dose.patient_id == patient.id, Dose.scheduled_for <= utcnow())
    doses = _filtered(query).order_by(Dose.scheduled_for.desc()).limit(_limit()).all()
    return jsonify([d.to_dict(patient.timezone) for d in doses])


@bp.get("/doses/<int:dose_id>")
@login_required
def get_dose(dose_id):
    patient = target_patient(g.user)
    dose = Dose.query.filter_by(id=dose_id, patient_id=patient.id).first()
    if not dose:
        raise ApiError("Dose not found.", 404, "not_found")
    return jsonify(dose.to_dict(patient.timezone))


@bp.post("/doses/<int:dose_id>/status")
@patient_only
def set_status(dose_id):
    new = str(json_body().get("status", "")).lower()
    if new not in DOSE_STATUSES:
        raise ApiError("status must be pending, taken or missed.", 400, "validation_error", {"status": "Invalid value."})
    dose = Dose.query.filter_by(id=dose_id, patient_id=g.user.id).first()  # other patients' doses look like "not found"
    if not dose:
        raise ApiError("Dose not found.", 404, "not_found")
    early = timedelta(minutes=current_app.config["EARLY_REPORT_MINUTES"])
    if new != "pending" and dose.scheduled_for - utcnow() > early:
        raise ApiError("This dose is too far in the future to report yet.", 409, "too_early")
    if new != dose.status:
        db.session.add(DoseStatusHistory(dose_id=dose.id, old_status=dose.status, new_status=new,
                                         source="patient_reported", changed_by=g.user.id))
        dose.status = new
        dose.status_source = "patient_reported" if new != "pending" else None
        dose.reported_at = utcnow() if new != "pending" else None  # the moment the PATIENT reported it
        db.session.commit()
    return jsonify(dose.to_dict(g.user.timezone))
