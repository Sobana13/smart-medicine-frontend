"""Sends WhatsApp messages through the OFFICIAL Meta WhatsApp Cloud API (no unofficial libraries).

Business-initiated messages must use pre-approved TEMPLATES, so we always send templates.
Every function returns a dict:  {"status": ..., "message_id": ..., "error": ...}
status is one of: demo_not_sent | not_configured | invalid_number | submitted | failed
IMPORTANT: "submitted" only means Meta accepted the request. Real delivery is confirmed later by the webhook.
"""
import logging
import re
import time

import requests
from flask import current_app

from utils import normalize_phone

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3          # first try + 2 retries for temporary problems (timeouts, 429, 5xx)
_sleep = time.sleep       # separate name so tests can replace it


def is_configured():
    cfg = current_app.config
    return all(cfg.get(k) for k in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_API_VERSION"))


def _result(status, message_id=None, error=None):
    return {"status": status, "message_id": message_id, "error": error}


def _clean(value):
    """Template values may not contain newlines, tabs or long runs of spaces."""
    text = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    return (re.sub(r" {2,}", " ", text).strip() or "-")[:200]


def _safe_error(resp):
    """Short error text from Meta's reply. Never includes headers or the access token."""
    try:
        err = resp.json().get("error", {})
        return f"HTTP {resp.status_code}, code {err.get('code', '?')}: {str(err.get('message', 'unknown error'))[:150]}"
    except Exception:
        return f"HTTP {resp.status_code}"


def send_template(to_number, template_name, params):
    cfg = current_app.config
    number = normalize_phone(to_number)
    if not number:
        return _result("invalid_number", error="Phone number must be in international format, e.g. +919876543210.")
    if cfg["DEMO_MODE"]:
        return _result("demo_not_sent", error="Demo mode is on. No message was sent.")
    if not is_configured():
        return _result("not_configured", error="WhatsApp credentials are not configured.")

    url = f"https://graph.facebook.com/{cfg['WHATSAPP_API_VERSION']}/{cfg['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    headers = {"Authorization": f"Bearer {cfg['WHATSAPP_ACCESS_TOKEN']}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": number.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": cfg["WHATSAPP_TEMPLATE_LANG"]},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": _clean(p)} for p in params]}],
        },
    }

    last_error = "Unknown error."
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.Timeout:
            last_error = "The request to WhatsApp timed out."
        except requests.RequestException:
            last_error = "Could not reach WhatsApp."
        else:
            if resp.status_code == 200:
                try:
                    return _result("submitted", message_id=resp.json()["messages"][0]["id"])
                except (KeyError, IndexError, ValueError):
                    return _result("failed", error="WhatsApp replied in an unexpected format.")
            last_error = _safe_error(resp)
            if resp.status_code != 429 and resp.status_code < 500:
                return _result("failed", error=last_error)  # permanent problem (bad template, bad token...): do not retry
        if attempt < MAX_ATTEMPTS - 1:
            _sleep(2 ** attempt)  # wait 1s, then 2s before retrying
    log.warning("WhatsApp send failed after %s attempts: %s", MAX_ATTEMPTS, last_error)
    return _result("failed", error=last_error)


# ---- Message builders. Parameter order matches {{1}}, {{2}}, {{3}} in your approved templates. ----
def send_reminder(number, medicine, dosage, time_text):
    return send_template(number, current_app.config["WHATSAPP_TEMPLATE_REMINDER"], [medicine, dosage, time_text])


def send_caregiver_alert(number, patient_name, medicine, time_text):
    return send_template(number, current_app.config["WHATSAPP_TEMPLATE_CAREGIVER"], [patient_name, medicine, time_text])


def send_test(number, time_text):
    # Re-uses the reminder template; the wording makes it obvious that it is only a test.
    return send_template(number, current_app.config["WHATSAPP_TEMPLATE_REMINDER"], ["TEST MESSAGE - no action needed", "n/a", time_text])
