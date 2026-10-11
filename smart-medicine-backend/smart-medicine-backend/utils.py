"""Small helpers: time zones, phone numbers and the ApiError exception."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class ApiError(Exception):
    """Raise this anywhere in a route. app.py turns it into a JSON error response."""

    def __init__(self, message, status=400, code="bad_request", details=None):
        super().__init__(message)
        self.message, self.status, self.code, self.details = message, status, code, details


# ---- Time: the database stores UTC (naive datetimes). We convert to the patient's zone only for display. ----
def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def valid_timezone(name):
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def to_local(dt_utc, tzname):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(get_tz(tzname))


def local_to_utc(day, hhmm, tzname):
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=get_tz(tzname)).astimezone(timezone.utc).replace(tzinfo=None)


def iso_local(dt_utc, tzname):
    return to_local(dt_utc, tzname).isoformat(timespec="seconds") if dt_utc else None


def local_today(tzname):
    return datetime.now(get_tz(tzname)).date()


# ---- Phone numbers: international (E.164) format, e.g. +919876543210 ----
_PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw):
    cleaned = re.sub(r"[\s\-().]", "", raw or "")
    return cleaned if _PHONE.match(cleaned) else None


def mask_phone(number):
    return ("*" * (len(number) - 4) + number[-4:]) if number and len(number) > 4 else ""
