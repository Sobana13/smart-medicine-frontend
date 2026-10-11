"""Database tables (SQLAlchemy models). One class = one table.
All timestamps are stored in UTC. 'local_date' / 'local_time' on a dose are the patient's own clock."""
import json
from extensions import db
from utils import iso_local, mask_phone, utcnow

DOSE_STATUSES = ("pending", "taken", "missed")


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)  # never the real password
    role = db.Column(db.String(10), nullable=False, default="patient")
    timezone = db.Column(db.String(64), nullable=False, default="Asia/Kolkata")
    whatsapp_number = db.Column(db.String(20))
    whatsapp_opt_in = db.Column(db.Boolean, nullable=False, default=False)  # patient agreed to receive WhatsApp messages
    whatsapp_opt_in_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.CheckConstraint("role IN ('patient','caregiver')", name="ck_users_role"),)

    medicines = db.relationship("Medicine", backref="patient", cascade="all, delete-orphan")
    preferences = db.relationship("NotificationPreference", uselist=False, backref="user", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "phone": self.phone,
                "role": self.role, "timezone": self.timezone}


class Medicine(db.Model):
    __tablename__ = "medicines"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    dosage = db.Column(db.String(100), nullable=False)       # exactly as prescribed; the app never suggests doses
    instructions = db.Column(db.String(300), default="")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    frequency = db.Column(db.String(10), nullable=False)      # once | twice | thrice | custom
    times_json = db.Column(db.Text, nullable=False)           # e.g. ["08:00","20:00"] in the patient's local time
    doctor = db.Column(db.String(100), default="")
    notes = db.Column(db.String(500), default="")
    reminders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.CheckConstraint("frequency IN ('once','twice','thrice','custom')", name="ck_med_frequency"),)

    doses = db.relationship("Dose", backref="medicine", cascade="all, delete-orphan")

    @property
    def times(self):
        return json.loads(self.times_json)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "dosage": self.dosage, "instructions": self.instructions or "",
                "start": self.start_date.isoformat(), "end": self.end_date.isoformat() if self.end_date else "",
                "frequency": self.frequency, "times": self.times, "doctor": self.doctor or "",
                "notes": self.notes or "", "remindersEnabled": self.reminders_enabled}


class Dose(db.Model):
    """One scheduled dose (e.g. Metformin on 2026-10-11 at 08:00). 'status' is what the PATIENT reported;
    nothing here proves the medicine was really taken."""
    __tablename__ = "doses"
    id = db.Column(db.Integer, primary_key=True)
    medicine_id = db.Column(db.Integer, db.ForeignKey("medicines.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scheduled_for = db.Column(db.DateTime, nullable=False)    # UTC
    local_date = db.Column(db.Date, nullable=False)
    local_time = db.Column(db.String(5), nullable=False)      # "08:00"
    status = db.Column(db.String(10), nullable=False, default="pending")
    status_source = db.Column(db.String(30))                  # patient_reported | grace_period_elapsed
    reported_at = db.Column(db.DateTime)
    __table_args__ = (
        db.UniqueConstraint("medicine_id", "scheduled_for", name="uq_dose_medicine_time"),  # no duplicate doses
        db.CheckConstraint("status IN ('pending','taken','missed')", name="ck_dose_status"),
        db.Index("ix_dose_patient_date", "patient_id", "local_date"),
        db.Index("ix_dose_status_time", "status", "scheduled_for"),
    )
    history = db.relationship("DoseStatusHistory", backref="dose", cascade="all, delete-orphan")

    def to_dict(self, tz):
        return {"id": self.id, "medicineId": self.medicine_id, "name": self.medicine.name, "dosage": self.medicine.dosage,
                "instructions": self.medicine.instructions or "", "date": self.local_date.isoformat(), "time": self.local_time,
                "scheduledAt": iso_local(self.scheduled_for, tz), "status": self.status, "statusSource": self.status_source,
                "reportedAt": iso_local(self.reported_at, tz),
                "verified": False,  # always false: the app cannot verify that medicine was actually consumed
                "demo": False}


class DoseStatusHistory(db.Model):
    __tablename__ = "dose_status_history"
    id = db.Column(db.Integer, primary_key=True)
    dose_id = db.Column(db.Integer, db.ForeignKey("doses.id"), nullable=False, index=True)
    old_status = db.Column(db.String(10), nullable=False)
    new_status = db.Column(db.String(10), nullable=False)
    source = db.Column(db.String(30), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"))  # null when the system changed it
    changed_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class CaregiverLink(db.Model):
    """A caregiver contact for a patient. Needs the patient's consent before any message is sent."""
    __tablename__ = "caregiver_links"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    caregiver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)  # set if the caregiver has an account
    name = db.Column(db.String(80), nullable=False)
    relationship = db.Column(db.String(50), default="")
    email = db.Column(db.String(254))
    whatsapp_number = db.Column(db.String(20))
    consent_given = db.Column(db.Boolean, nullable=False, default=False)   # patient agrees to share data
    consent_at = db.Column(db.DateTime)
    recipient_opt_in = db.Column(db.Boolean, nullable=False, default=False)  # caregiver agreed to get WhatsApp messages
    notify_missed = db.Column(db.Boolean, nullable=False, default=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint("patient_id", "whatsapp_number", name="uq_link_patient_number"),)

    def to_dict(self, caregiver_view=False):
        d = {"id": self.id, "patientId": self.patient_id, "name": self.name, "relationship": self.relationship or "",
             "email": self.email or "", "consent": self.consent_given, "recipientOptIn": self.recipient_opt_in,
             "notifyMissed": self.notify_missed, "active": self.active, "hasAccount": self.caregiver_user_id is not None}
        if caregiver_view:
            patient = db.session.get(User, self.patient_id)
            d["patientName"] = patient.name if patient else ""
        else:
            d["whatsappNumber"] = self.whatsapp_number or ""
        return d


class NotificationRecord(db.Model):
    """One WhatsApp attempt. 'event_key' is unique, which is how we stop duplicate reminders/alerts."""
    __tablename__ = "notification_records"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    dose_id = db.Column(db.Integer, db.ForeignKey("doses.id", ondelete="SET NULL"))
    type = db.Column(db.String(20), nullable=False)               # reminder | caregiver_missed | test
    recipient_category = db.Column(db.String(10), nullable=False)  # patient | caregiver
    recipient_masked = db.Column(db.String(20), nullable=False)    # +*********3210 (never the full number)
    event_key = db.Column(db.String(80), unique=True)              # e.g. "reminder:42:patient"
    wa_message_id = db.Column(db.String(120), index=True)
    submit_status = db.Column(db.String(20), nullable=False, default="queued")  # queued|submitted|failed|demo_not_sent|not_configured|invalid_number
    delivery_status = db.Column(db.String(20))                     # sent|delivered|read|failed (from the webhook only)
    error = db.Column(db.String(300))                              # safe text, never contains tokens
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime)

    def to_dict(self, tz):
        label = {"reminder": "Medicine reminder", "caregiver_missed": "Missed-dose alert", "test": "Test message"}.get(self.type, self.type)
        who = "caregiver" if self.recipient_category == "caregiver" else "patient"
        return {"id": self.id, "type": self.type, "recipientCategory": self.recipient_category, "recipient": self.recipient_masked,
                "doseId": self.dose_id, "createdAt": iso_local(self.created_at, tz), "submitStatus": self.submit_status,
                "deliveryStatus": self.delivery_status, "error": self.error,
                "text": f"{label} to {who}: {self.submit_status}" + (f", delivery {self.delivery_status}" if self.delivery_status else ""),
                "at": iso_local(self.created_at, tz)}


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    reminders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    caregiver_alerts_enabled = db.Column(db.Boolean, nullable=False, default=True)
