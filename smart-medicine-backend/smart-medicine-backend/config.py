"""Settings. Values come from the .env file (see .env.example). Nothing secret is written here."""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    PRODUCTION = APP_ENV == "production"
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///medicine.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTO_CREATE_DB = _bool("AUTO_CREATE_DB", True)  # set false once you use migrations

    # Requests / cookies
    MAX_CONTENT_LENGTH = 64 * 1024  # reject request bodies larger than 64 KB
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = PRODUCTION  # cookies only over HTTPS in production
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",") if o.strip()]

    # Medicine rules
    DEFAULT_TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
    GRACE_PERIOD_MINUTES = _int("GRACE_PERIOD_MINUTES", 30)
    EARLY_REPORT_MINUTES = _int("EARLY_REPORT_MINUTES", 120)

    # Scheduler
    SCHEDULER_ENABLED = _bool("SCHEDULER_ENABLED", True)
    SCHEDULER_INTERVAL_SECONDS = _int("SCHEDULER_INTERVAL_SECONDS", 60)

    # WhatsApp (read at call time, never returned by any API)
    DEMO_MODE = _bool("DEMO_MODE", True)
    WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
    WHATSAPP_TEMPLATE_REMINDER = os.getenv("WHATSAPP_TEMPLATE_REMINDER", "medicine_reminder")
    WHATSAPP_TEMPLATE_CAREGIVER = os.getenv("WHATSAPP_TEMPLATE_CAREGIVER", "caregiver_missed_alert")
    WHATSAPP_TEMPLATE_LANG = os.getenv("WHATSAPP_TEMPLATE_LANG", "en")


class TestConfig(Config):
    """Used by pytest only: in-memory database, no scheduler, no real WhatsApp, ignores your .env."""
    TESTING = True
    PRODUCTION = False
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AUTO_CREATE_DB = False
    SCHEDULER_ENABLED = False
    SESSION_COOKIE_SECURE = False
    DEMO_MODE = False
    GRACE_PERIOD_MINUTES = 30
    EARLY_REPORT_MINUTES = 120
    DEFAULT_TIMEZONE = "Asia/Kolkata"
    WHATSAPP_ACCESS_TOKEN = ""
    WHATSAPP_PHONE_NUMBER_ID = ""
    WHATSAPP_VERIFY_TOKEN = ""
    WHATSAPP_APP_SECRET = ""
