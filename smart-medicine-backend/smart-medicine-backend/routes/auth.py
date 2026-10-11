"""Register, log in, log out, who am I. Passwords are hashed with Werkzeug and never stored or returned."""
import re
import time
from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import CaregiverLink, NotificationPreference, User
from security import current_user, json_body
from utils import ApiError, normalize_phone

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY_HASH = generate_password_hash("not-a-real-password")  # lets us spend equal time when the email is unknown
_failures = {}  # (ip, email) -> list of timestamps. Simple in-memory brute-force limiter (use Redis in big deployments)
MAX_FAILS, WINDOW = 5, 15 * 60


def _too_many_attempts(key):
    now = time.time()
    _failures[key] = [t for t in _failures.get(key, []) if now - t < WINDOW]
    return len(_failures[key]) >= MAX_FAILS


@bp.post("/register")
def register():
    data = json_body()
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    phone = normalize_phone(str(data.get("phone", "")))
    password = str(data.get("password", ""))
    role = str(data.get("role", "patient")).lower()
    errors = {}
    if not 2 <= len(name) <= 80: errors["name"] = "Enter your full name (2 to 80 characters)."
    if not EMAIL_RE.match(email) or len(email) > 254: errors["email"] = "Enter a valid email address."
    if not phone: errors["phone"] = "Use international format, for example +919876543210."
    if not 8 <= len(password) <= 128: errors["password"] = "Password must be 8 to 128 characters."
    if role not in ("patient", "caregiver"): errors["role"] = "Role must be patient or caregiver."
    if errors:
        raise ApiError("Please fix the highlighted fields.", 400, "validation_error", errors)
    if User.query.filter(func.lower(User.email) == email).first():
        raise ApiError("An account with this email already exists.", 409, "duplicate_email", {"email": "Already registered."})

    user = User(name=name, email=email, phone=phone, role=role, password_hash=generate_password_hash(password),
                timezone=current_app.config["DEFAULT_TIMEZONE"])
    user.preferences = NotificationPreference()
    db.session.add(user)
    try:
        db.session.flush()
        if role == "caregiver":  # attach links that patients created earlier for this email
            for link in CaregiverLink.query.filter(func.lower(CaregiverLink.email) == email, CaregiverLink.caregiver_user_id.is_(None)):
                link.caregiver_user_id = user.id
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ApiError("An account with this email already exists.", 409, "duplicate_email", {"email": "Already registered."})
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    return jsonify({"user": user.to_dict()}), 201


@bp.post("/login")
def login():
    data = json_body()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    key = (request.remote_addr, email)
    if _too_many_attempts(key):
        raise ApiError("Too many failed attempts. Please wait 15 minutes and try again.", 429, "rate_limited")
    user = User.query.filter(func.lower(User.email) == email).first()
    ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if not (user and ok):
        _failures.setdefault(key, []).append(time.time())
        raise ApiError("Incorrect email or password.", 401, "invalid_credentials")  # same message for both cases
    _failures.pop(key, None)
    session.clear()  # new session on login prevents session fixation
    session["user_id"] = user.id
    session.permanent = True
    return jsonify({"user": user.to_dict()})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})


@bp.get("/me")
def me():
    user = current_user()
    if not user:
        raise ApiError("Please log in to continue.", 401, "unauthenticated")
    return jsonify({"user": user.to_dict()})
