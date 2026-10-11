"""Shared pytest setup: a fresh in-memory database for every test. No real WhatsApp messages can be sent."""
from datetime import timedelta

import pytest

from app import create_app
from config import TestConfig
from extensions import db
from models import Dose, Medicine, User
from routes import auth
from utils import local_today, to_local, utcnow


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def reset_login_limiter():
    auth._failures.clear()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, email="pat@example.com", name="Pat Patient", role="patient", password="secret123", phone="+919876543210"):
    return client.post("/api/auth/register", json={"name": name, "email": email, "phone": phone, "password": password, "role": role})


MED = {"name": "Metformin", "dosage": "500 mg tablet", "instructions": "After food", "start": "2026-01-01", "end": "",
       "frequency": "twice", "times": ["08:00", "20:00"], "doctor": "Dr. Rao", "notes": "", "remindersEnabled": True}


def make_dose(email, minutes=-10, status="pending", name="Metformin"):
    """Insert a medicine + one dose directly in the database. The medicine has already ended, so the
    scheduler never adds extra doses and the counts in tests stay exact."""
    user = User.query.filter_by(email=email).first()
    start = local_today(user.timezone) - timedelta(days=3)
    med = Medicine(patient_id=user.id, name=name, dosage="500 mg", start_date=start, end_date=start, frequency="once",
                   times_json='["08:00"]', created_at=utcnow() - timedelta(days=3))
    db.session.add(med)
    db.session.flush()
    when = utcnow() + timedelta(minutes=minutes)
    local = to_local(when, user.timezone)
    dose = Dose(medicine_id=med.id, patient_id=user.id, scheduled_for=when, local_date=local.date(),
                local_time=local.strftime("%H:%M"), status=status)
    db.session.add(dose)
    db.session.commit()
    return dose.id
