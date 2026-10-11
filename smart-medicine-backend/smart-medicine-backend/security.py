"""Login checks and permission helpers used by every protected route."""
from functools import wraps
from flask import g, request, session
from extensions import db
from models import CaregiverLink, User
from utils import ApiError


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            raise ApiError("Please log in to continue.", 401, "unauthenticated")
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def patient_only(fn):
    """Only the patient themself may use this route (caregivers are read-only)."""
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if g.user.role != "patient":
            raise ApiError("Only the patient can do this.", 403, "forbidden")
        return fn(*args, **kwargs)
    return wrapper


def target_patient(user):
    """Whose data is this request about?
    - A patient always sees their own data.
    - A caregiver must pass ?patientId=<id> AND have an active, consented link to that patient."""
    if user.role == "patient":
        return user
    pid = request.args.get("patientId", type=int)
    if not pid:
        raise ApiError("patientId is required for caregivers.", 400, "validation_error")
    link = CaregiverLink.query.filter_by(patient_id=pid, caregiver_user_id=user.id, active=True, consent_given=True).first()
    if not link:
        raise ApiError("You are not linked to that patient.", 403, "forbidden")
    return db.session.get(User, pid)


def json_body():
    """Return the JSON object sent by the client. Requiring JSON also blocks simple cross-site form posts (CSRF)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON object with Content-Type: application/json.", 400, "invalid_json")
    return data
