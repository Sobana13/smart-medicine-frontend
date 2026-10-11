"""Medicine CRUD. The patient types in what the DOCTOR prescribed. This app never suggests or changes dosages."""
import json
import re
from datetime import date
from flask import Blueprint, g, jsonify

from extensions import db
from models import Dose, Medicine, NotificationRecord
from security import json_body, login_required, patient_only, target_patient
from services.reminder_service import rebuild_future_doses
from utils import ApiError

bp = Blueprint("medicines", __name__, url_prefix="/api/medicines")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FREQ_COUNT = {"once": 1, "twice": 2, "thrice": 3}


def _date(value, field, errors, required=True):
    if value in (None, ""):
        if required: errors[field] = "This date is required."
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors[field] = "Use the format YYYY-MM-DD."
        return None


def clean_medicine(data):
    """Validate the request body and return clean values. Raises a 400 listing every problem."""
    errors = {}
    name, dosage = str(data.get("name", "")).strip(), str(data.get("dosage", "")).strip()
    if not 1 <= len(name) <= 100: errors["name"] = "Medicine name is required (max 100 characters)."
    if not 1 <= len(dosage) <= 100: errors["dosage"] = "Enter the dosage exactly as prescribed (max 100 characters)."
    instructions, doctor, notes = (str(data.get(k, "") or "").strip() for k in ("instructions", "doctor", "notes"))
    if len(instructions) > 300: errors["instructions"] = "Max 300 characters."
    if len(doctor) > 100: errors["doctor"] = "Max 100 characters."
    if len(notes) > 500: errors["notes"] = "Max 500 characters."
    start = _date(data.get("start", data.get("startDate")), "start", errors)
    end = _date(data.get("end", data.get("endDate")), "end", errors, required=False)
    if start and end and end < start: errors["end"] = "End date cannot be before the start date."
    frequency = str(data.get("frequency", "")).lower()
    if frequency not in ("once", "twice", "thrice", "custom"): errors["frequency"] = "Choose once, twice, thrice or custom."
    times = data.get("times", [data["time"]] if "time" in data else [])
    if not isinstance(times, list) or not all(isinstance(t, str) and TIME_RE.match(t) for t in times):
        errors["times"] = "Use 24-hour times like 08:00."
    else:
        times = sorted(set(times))
        if frequency in FREQ_COUNT and len(times) != FREQ_COUNT[frequency]:
            errors["times"] = f"'{frequency}' needs exactly {FREQ_COUNT[frequency]} reminder time(s)."
        elif frequency == "custom" and not 1 <= len(times) <= 8:
            errors["times"] = "Custom schedules need 1 to 8 reminder times."
    reminders = data.get("remindersEnabled", True)
    if not isinstance(reminders, bool): errors["remindersEnabled"] = "Must be true or false."
    if errors:
        raise ApiError("Please fix the highlighted fields.", 400, "validation_error", errors)
    return dict(name=name, dosage=dosage, instructions=instructions, start_date=start, end_date=end, frequency=frequency,
                times_json=json.dumps(times), doctor=doctor, notes=notes, reminders_enabled=reminders)


def _own_medicine(med_id, patient):
    med = db.session.get(Medicine, med_id)
    if not med or med.patient_id != patient.id:
        raise ApiError("Medicine not found.", 404, "not_found")  # 404 (not 403) so IDs of other patients are not revealed
    return med


@bp.get("")
@login_required
def list_medicines():
    patient = target_patient(g.user)
    meds = Medicine.query.filter_by(patient_id=patient.id).order_by(Medicine.name).all()
    return jsonify([m.to_dict() for m in meds])


@bp.post("")
@patient_only
def add_medicine():
    med = Medicine(patient_id=g.user.id, **clean_medicine(json_body()))
    db.session.add(med)
    db.session.commit()
    rebuild_future_doses(med)
    return jsonify(med.to_dict()), 201


@bp.get("/<int:med_id>")
@login_required
def get_medicine(med_id):
    return jsonify(_own_medicine(med_id, target_patient(g.user)).to_dict())


@bp.put("/<int:med_id>")
@patient_only
def update_medicine(med_id):
    med = _own_medicine(med_id, g.user)
    for key, value in clean_medicine(json_body()).items():
        setattr(med, key, value)
    db.session.commit()
    rebuild_future_doses(med)
    return jsonify(med.to_dict())


@bp.delete("/<int:med_id>")
@patient_only
def delete_medicine(med_id):
    med = _own_medicine(med_id, g.user)
    ids = [d.id for d in med.doses]
    if ids:  # keep the notification log, just unlink it from the deleted doses
        NotificationRecord.query.filter(NotificationRecord.dose_id.in_(ids)).update({"dose_id": None}, synchronize_session=False)
    db.session.delete(med)
    db.session.commit()
    return jsonify({"deleted": med_id})
