"""Caregiver links. A patient adds a caregiver (with consent). Caregivers can then VIEW that patient's data."""
from flask import Blueprint, g, jsonify
from sqlalchemy import func

from extensions import db
from models import CaregiverLink, User
from routes.auth import EMAIL_RE
from security import json_body, login_required, patient_only
from utils import ApiError, normalize_phone, utcnow

bp = Blueprint("caregivers", __name__, url_prefix="/api/caregivers")


def _clean(data, creating):
    errors, out = {}, {}
    name = str(data.get("name", "")).strip()
    if not 2 <= len(name) <= 80: errors["name"] = "Enter the caregiver's name."
    out["name"] = name
    out["relationship"] = str(data.get("relationship", "")).strip()[:50]
    email = str(data.get("email", "") or "").strip().lower()
    if email and not EMAIL_RE.match(email): errors["email"] = "Enter a valid email address."
    out["email"] = email or None
    number = normalize_phone(str(data.get("whatsappNumber", "")))
    if not number: errors["whatsappNumber"] = "Use international format, for example +919876543210."
    out["whatsapp_number"] = number
    consent, opt_in = data.get("consent"), data.get("recipientOptIn")
    if creating and consent is not True:
        errors["consent"] = "The patient must agree to share medication information with this caregiver."
    if not isinstance(data.get("notifyMissed", True), bool): errors["notifyMissed"] = "Must be true or false."
    if errors:
        raise ApiError("Please fix the highlighted fields.", 400, "validation_error", errors)
    out["notify_missed"] = data.get("notifyMissed", True)
    if "consent" in data: out["consent_given"] = bool(consent)
    if "recipientOptIn" in data: out["recipient_opt_in"] = bool(opt_in)
    return out


@bp.get("")
@login_required
def list_links():
    if g.user.role == "caregiver":  # a caregiver sees the patients who linked them
        links = CaregiverLink.query.filter_by(caregiver_user_id=g.user.id, active=True, consent_given=True).all()
        return jsonify([l.to_dict(caregiver_view=True) for l in links])
    return jsonify([l.to_dict() for l in CaregiverLink.query.filter_by(patient_id=g.user.id).order_by(CaregiverLink.name)])


@bp.post("")
@patient_only
def add_link():
    values = _clean(json_body(), creating=True)
    if CaregiverLink.query.filter_by(patient_id=g.user.id, whatsapp_number=values["whatsapp_number"]).first():
        raise ApiError("This caregiver number is already linked.", 409, "duplicate")
    link = CaregiverLink(patient_id=g.user.id, consent_at=utcnow(), **values)
    if link.email:
        account = User.query.filter(func.lower(User.email) == link.email, User.role == "caregiver").first()
        link.caregiver_user_id = account.id if account else None
    db.session.add(link)
    db.session.commit()
    return jsonify(link.to_dict()), 201


def _own_link(link_id):
    link = CaregiverLink.query.filter_by(id=link_id, patient_id=g.user.id).first()
    if not link:
        raise ApiError("Caregiver not found.", 404, "not_found")
    return link


@bp.put("/<int:link_id>")
@patient_only
def update_link(link_id):
    link = _own_link(link_id)
    for key, value in _clean(json_body(), creating=False).items():
        setattr(link, key, value)
    if not link.consent_given:  # withdrawing consent switches everything off
        link.notify_missed = False
    elif link.consent_at is None:
        link.consent_at = utcnow()
    db.session.commit()
    return jsonify(link.to_dict())


@bp.delete("/<int:link_id>")
@patient_only
def delete_link(link_id):
    link = _own_link(link_id)
    db.session.delete(link)
    db.session.commit()
    return jsonify({"deleted": link_id})
