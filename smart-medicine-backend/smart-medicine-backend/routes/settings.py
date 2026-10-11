"""User + notification settings. Never returns any WhatsApp secret, only yes/no flags."""
from datetime import datetime
from flask import Blueprint, current_app, g, jsonify

from extensions import db
from models import CaregiverLink, NotificationPreference
from security import json_body, patient_only, login_required
from services import whatsapp_service as wa
from utils import ApiError, normalize_phone, utcnow, valid_timezone

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


def _view(user):
    prefs = user.preferences or NotificationPreference(reminders_enabled=True, caregiver_alerts_enabled=True)
    first = CaregiverLink.query.filter_by(patient_id=user.id).order_by(CaregiverLink.id).first() if user.role == "patient" else None
    return {
        "patientName": user.name, "email": user.email, "phone": user.phone, "timezone": user.timezone,
        "patientWhatsapp": user.whatsapp_number or "", "whatsappOptIn": user.whatsapp_opt_in,
        "remindersEnabled": prefs.reminders_enabled, "caregiverAlertsEnabled": prefs.caregiver_alerts_enabled,
        "caregiverName": first.name if first else "", "caregiverWhatsapp": (first.whatsapp_number or "") if first else "",
        "graceMinutes": current_app.config["GRACE_PERIOD_MINUTES"],
        "demoMode": current_app.config["DEMO_MODE"], "whatsappConfigured": wa.is_configured(),
    }


@bp.get("")
@login_required
def get_settings():
    return jsonify(_view(g.user))


@bp.put("")
@patient_only
def update_settings():
    data, user, errors = json_body(), g.user, {}
    if "patientName" in data:
        name = str(data["patientName"]).strip()
        if 2 <= len(name) <= 80: user.name = name
        else: errors["patientName"] = "Enter your full name."
    if "timezone" in data:
        if valid_timezone(str(data["timezone"])): user.timezone = str(data["timezone"])
        else: errors["timezone"] = "Unknown time zone, for example Asia/Kolkata."
    if "patientWhatsapp" in data:
        raw = str(data["patientWhatsapp"] or "").strip()
        number = normalize_phone(raw) if raw else None
        if raw and not number: errors["patientWhatsapp"] = "Use international format, for example +919876543210."
        else: user.whatsapp_number = number
    if "whatsappOptIn" in data:
        if not isinstance(data["whatsappOptIn"], bool): errors["whatsappOptIn"] = "Must be true or false."
        elif data["whatsappOptIn"] and not user.whatsapp_number: errors["whatsappOptIn"] = "Add your WhatsApp number first."
        else:
            user.whatsapp_opt_in = data["whatsappOptIn"]
            user.whatsapp_opt_in_at = utcnow() if data["whatsappOptIn"] else None
    prefs = user.preferences or NotificationPreference(user_id=user.id)
    for key, attr in (("remindersEnabled", "reminders_enabled"), ("caregiverAlertsEnabled", "caregiver_alerts_enabled")):
        if key in data:
            if isinstance(data[key], bool): setattr(prefs, attr, data[key])
            else: errors[key] = "Must be true or false."
    if errors:
        db.session.rollback()
        raise ApiError("Please fix the highlighted fields.", 400, "validation_error", errors)
    db.session.add(prefs)
    db.session.commit()
    return jsonify(_view(user))
