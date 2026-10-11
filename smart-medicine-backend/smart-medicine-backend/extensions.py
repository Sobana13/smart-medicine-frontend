"""Shared extension objects. They are created here and connected to the app in app.py."""
import sqlite3
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()


@event.listens_for(Engine, "connect")
def _sqlite_settings(dbapi_connection, _record):
    """SQLite ignores foreign keys unless asked. WAL mode lets the scheduler and web requests share the file."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()
