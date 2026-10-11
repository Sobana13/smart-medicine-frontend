"""Creates scheduled doses, sends reminders, finds missed doses and alerts caregivers.

run_cycle() is called every minute by APScheduler. It is safe to run twice at the same time because:
  * doses have a UNIQUE (medicine, time) constraint  -> no duplicate doses
  * notifications have a UNIQUE event_key            -> no duplicate WhatsApp messages
"""
import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import CaregiverLink, Dose, DoseStatusHistory, Medicine, NotificationRecord, User
from services import whatsapp_service as wa
from utils import local_today, local_to_utc, mask_phone, utcnow

log = logging.getLogger(__name__)
STALE_ALERT_HOURS = 6  # never alert caregivers about doses that went missed long ago (e.g. server was off)


def grace_minutes():
    return current_app.config["GRACE_PERIOD_MINUTES"]


# ---------- Dose generation ----------
def ensure_doses(patient, day, not_before=None):
    """Create Dose rows for one local date. Calling it again changes nothing (idempotent).
    not_before: skip times earlier than this UTC moment (used after editing a medicine)."""
    existing = {(d.medicine_id, d.scheduled_for) for d in Dose.query.filter_by(patient_id=patient.id, local_date=day)}
    created = False
    for med in Medicine.query.filter_by(patient_id=patient.id):
        if day < med.start_date or (med.end_date and day > med.end_date):
            continue
        for hhmm in med.times:
            when = local_to_utc(day, hhmm, patient.timezone)
            if (med.id, when) in existing or when < med.created_at or (not_before and when < not_before):
                continue  # already there, or in the past (we never invent past doses)
            db.session.add(Dose(medicine_id=med.id, patient_id=patient.id, scheduled_for=when, local_date=day, local_time=hhmm))
            created = True
    if created:
        try:
            db.session.commit()
        except IntegrityError:  # another process created them first
            db.session.rollback()


def rebuild_future_doses(medicine):
    """After a medicine is added or edited: drop untouched future doses and generate them again."""
    patient = db.session.get(User, medicine.patient_id)
    for dose in Dose.query.filter(Dose.medicine_id == medicine.id, Dose.status == "pending", Dose.scheduled_for > utcnow()):
        db.session.delete(dose)
    db.session.commit()
    today = local_today(patient.timezone)
    for offset in (0, 1):
        ensure_doses(patient, today + timedelta(days=offset), not_before=utcnow())


# ---------- Notifications ----------
def dispatch(patient_id, dose_id, ntype, category, number, key, send_fn):
    """Claim the event_key FIRST, then send. If the key already exists, someone else handled this event."""
    record = NotificationRecord(patient_id=patient_id, dose_id=dose_id, type=ntype, recipient_category=category,
                                recipient_masked=mask_phone(number), event_key=key, submit_status="queued")
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None
    result = send_fn()
    record.submit_status = result["status"]
    record.wa_message_id = result["message_id"]
    record.error = result["error"]
    record.updated_at = utcnow()
    db.session.commit()
    return record


def send_due_reminders(now):
    window = timedelta(minutes=grace_minutes())
    for patient in User.query.filter_by(role="patient").all():
        ensure_doses(patient, local_today(patient.timezone))
        prefs = patient.preferences
        if not (prefs and prefs.reminders_enabled and patient.whatsapp_opt_in and patient.whatsapp_number):
            continue
        due = (Dose.query.join(Medicine).filter(
            Dose.patient_id == patient.id, Dose.status == "pending", Dose.scheduled_for <= now,
            Dose.scheduled_for >= now - window, Medicine.reminders_enabled.is_(True)).all())
        for dose in due:
            when = f"{dose.local_time} ({patient.timezone})"
            dispatch(patient.id, dose.id, "reminder", "patient", patient.whatsapp_number, f"reminder:{dose.id}:patient",
                     lambda d=dose, w=when, p=patient: wa.send_reminder(p.whatsapp_number, d.medicine.name, d.medicine.dosage, w))


def mark_missed(now):
    """A dose becomes 'missed' only AFTER the grace period passes with no confirmation."""
    cutoff = now - timedelta(minutes=grace_minutes())
    doses = Dose.query.filter(Dose.status == "pending", Dose.scheduled_for < cutoff).all()
    for dose in doses:
        dose.status, dose.status_source = "missed", "grace_period_elapsed"
        db.session.add(DoseStatusHistory(dose_id=dose.id, old_status="pending", new_status="missed", source="grace_period_elapsed"))
    db.session.commit()
    return doses


def notify_caregivers(missed_doses, now):
    for dose in missed_doses:
        if dose.scheduled_for < now - timedelta(hours=STALE_ALERT_HOURS):
            continue
        patient = db.session.get(User, dose.patient_id)
        if not (patient.preferences and patient.preferences.caregiver_alerts_enabled):
            continue
        links = CaregiverLink.query.filter_by(patient_id=patient.id, active=True, consent_given=True,
                                              recipient_opt_in=True, notify_missed=True).all()
        for link in links:
            if not link.whatsapp_number:
                continue
            when = f"{dose.local_time} ({patient.timezone})"
            dispatch(patient.id, dose.id, "caregiver_missed", "caregiver", link.whatsapp_number, f"missed:{dose.id}:{link.id}",
                     lambda l=link, d=dose, w=when, p=patient: wa.send_caregiver_alert(l.whatsapp_number, p.name, d.medicine.name, w))


def run_cycle(app):
    """One scheduler tick. Logs counts only, never medicine names or phone numbers."""
    with app.app_context():
        try:
            now = utcnow()
            send_due_reminders(now)
            missed = mark_missed(now)
            notify_caregivers(missed, now)
            if missed:
                log.info("Marked %s dose(s) as missed after the grace period.", len(missed))
        except Exception:
            db.session.rollback()
            log.exception("Reminder cycle failed")  # stack trace only, no patient data


def start_scheduler(app):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(run_cycle, "interval", args=[app], seconds=app.config["SCHEDULER_INTERVAL_SECONDS"],
                      id="medicine_cycle", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
