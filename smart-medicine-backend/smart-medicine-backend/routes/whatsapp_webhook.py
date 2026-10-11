"""Webhook that Meta calls. GET = one-time verification. POST = delivery-status updates (sent/delivered/read/failed).
Only API acceptance + these webhook statuses tell us what really happened to a message."""
import hashlib
import hmac
import logging
from flask import Blueprint, current_app, jsonify, request

from extensions import db
from models import NotificationRecord
from utils import utcnow

bp = Blueprint("whatsapp_webhook", __name__, url_prefix="/api/whatsapp")
log = logging.getLogger(__name__)
RANK = {"sent": 1, "delivered": 2, "read": 3}  # delivery only moves forward, so repeated/out-of-order webhooks are harmless


@bp.get("/webhook")
def verify():
    token = current_app.config["WHATSAPP_VERIFY_TOKEN"]
    sent = request.args.get("hub.verify_token", "")
    if token and request.args.get("hub.mode") == "subscribe" and hmac.compare_digest(sent, token):
        return request.args.get("hub.challenge", ""), 200, {"Content-Type": "text/plain"}
    return jsonify({"error": "Webhook verification failed.", "code": "forbidden"}), 403


def _signature_ok(raw_body):
    secret = current_app.config["WHATSAPP_APP_SECRET"]
    header = request.headers.get("X-Hub-Signature-256", "")
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], expected)


def _apply_status(status):
    record = NotificationRecord.query.filter_by(wa_message_id=status.get("id")).first() if status.get("id") else None
    if not record:
        return
    new, current = status.get("status"), RANK.get(record.delivery_status, 0)
    if new in RANK and RANK[new] > current:
        record.delivery_status = new
    elif new == "failed" and current < RANK["delivered"]:
        record.delivery_status = "failed"
        err = (status.get("errors") or [{}])[0]
        record.error = f"WhatsApp error {err.get('code', '?')}: {str(err.get('title', 'delivery failed'))[:150]}"
    else:
        return
    record.updated_at = utcnow()


@bp.post("/webhook")
def receive():
    raw = request.get_data()  # exact bytes Meta signed
    if not _signature_ok(raw):
        return jsonify({"error": "Invalid signature.", "code": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for status in (change.get("value") or {}).get("statuses", []):
                _apply_status(status)
    db.session.commit()
    return jsonify({"received": True}), 200  # always 200 for valid signatures so Meta does not keep retrying
