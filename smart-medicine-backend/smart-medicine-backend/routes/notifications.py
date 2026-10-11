"""Notification history and the WhatsApp test endpoint."""
from datetime import timedelta

from flask import Blueprint, current_app, g, jsonify, request

from extensions import db
from models import CaregiverLink, NotificationRecord
from security import json_body, login_required, patient_only, target_patient
from services import whatsapp_service as wa
from services.reminder_service import dispatch
from utils import ApiError, to_local, utcnow

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")
MAX_TESTS_PER_HOUR = 5


@bp.get("")
@login_required
def list_notifications():
    patient = target_patient(g.user)
    limit = max(1, min(request.args.get("limit", 50, type=int), 200))
    rows = NotificationRecord.query.filter_by(patient_id=patient.id).order_by(NotificationRecord.created_at.desc()).limit(limit).all()
    return jsonify([r.to_dict(patient.timezone) for r in rows])


@bp.get("/<int:note_id>")
@login_required
def get_notification(note_id):
    patient = target_patient(g.user)
    row = NotificationRecord.query.filter_by(id=note_id, patient_id=patient.id).first()
    if not row:
        raise ApiError("Notification not found.", 404, "not_found")
    return jsonify(row.to_dict(patient.timezone))


@bp.post("/test")
@patient_only
def send_test():
    """Sends a REAL test message only when DEMO_MODE=false and all WhatsApp settings exist. Never pretends otherwise."""
    data = json_body()
    cfg = current_app.config
    if cfg["DEMO_MODE"]:
        raise ApiError("Demo mode is on, so no message was sent. Set DEMO_MODE=false in .env to send real messages.", 503, "demo_mode")
    if not wa.is_configured():
        raise ApiError("The WhatsApp service is not configured. Add the WHATSAPP_* values to .env. No message was sent.", 503, "whatsapp_not_configured")

    target = str(data.get("target", "patient")).lower()
    if target == "caregiver":
        link = CaregiverLink.query.filter_by(id=data.get("caregiverId"), patient_id=g.user.id).first()
        if not link:
            raise ApiError("Caregiver not found.", 404, "not_found")
        if not (link.consent_given and link.recipient_opt_in and link.whatsapp_number):
            raise ApiError("This caregiver has not given consent and opted in to WhatsApp messages.", 400, "no_opt_in")
        number, category = link.whatsapp_number, "caregiver"
    elif target == "patient":
        if not (g.user.whatsapp_opt_in and g.user.whatsapp_number):
            raise ApiError("Add your WhatsApp number and opt in under Settings first.", 400, "no_opt_in")
        number, category = g.user.whatsapp_number, "patient"
    else:
        raise ApiError("target must be 'patient' or 'caregiver'.", 400, "validation_error")

    recent = NotificationRecord.query.filter(NotificationRecord.patient_id == g.user.id, NotificationRecord.type == "test",
                                             NotificationRecord.created_at > utcnow() - timedelta(hours=1)).count()
    if recent >= MAX_TESTS_PER_HOUR:
        raise ApiError("Too many test messages. Try again later.", 429, "rate_limited")

    clock = to_local(utcnow(), g.user.timezone).strftime("%H:%M")
    record = dispatch(g.user.id, None, "test", category, number, None, lambda: wa.send_test(number, clock))
    body = record.to_dict(g.user.timezone)
    if record.submit_status != "submitted":
        return jsonify({"error": record.error or "The message could not be sent.", "code": "send_failed", "notification": body}), 502
    body["note"] = "WhatsApp accepted the message. Delivery is confirmed later by the webhook."
    return jsonify(body), 202
