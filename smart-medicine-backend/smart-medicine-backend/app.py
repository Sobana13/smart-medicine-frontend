"""Flask application factory. Run with:  python app.py   (or: flask --app app run)"""
import logging
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import Config
from extensions import cors, db, migrate
from utils import ApiError


def create_app(config_class=Config, start_scheduler=None):
    app = Flask(__name__)
    app.config.from_object(config_class)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if app.config["PRODUCTION"]:
        if len(app.config["SECRET_KEY"]) < 32 or "REPLACE_ME" in app.config["SECRET_KEY"]:
            raise RuntimeError("Set a long random SECRET_KEY in .env before running in production.")
        if "*" in app.config["CORS_ORIGINS"]:
            raise RuntimeError("CORS_ORIGINS must list your exact frontend address(es) in production, never '*'.")
    elif not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = "dev-only-insecure-key"  # fine on your laptop, refused in production

    db.init_app(app)
    migrate.init_app(app, db)
    # Only the listed frontend origins may call the API with cookies.
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}}, supports_credentials=True)

    from routes import auth, caregivers, dashboard, doses, medicines, notifications, settings, whatsapp_webhook
    for module in (auth, medicines, doses, dashboard, caregivers, notifications, settings, whatsapp_webhook):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def api_error(err):
        body = {"error": err.message, "code": err.code}
        if err.details:
            body["details"] = err.details
        return jsonify(body), err.status

    @app.errorhandler(HTTPException)
    def http_error(err):
        return jsonify({"error": err.description, "code": err.name.lower().replace(" ", "_")}), err.code

    @app.errorhandler(Exception)
    def server_error(err):
        db.session.rollback()
        app.logger.exception("Unhandled error")  # stack trace only; request bodies are never logged
        return jsonify({"error": "Something went wrong on the server.", "code": "server_error"}), 500

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cache-Control"] = "no-store"  # medical data must not be cached by browsers/proxies
        return resp

    if app.config["AUTO_CREATE_DB"]:
        with app.app_context():
            db.create_all()  # development convenience; see README for migrations

    # --- Scheduler: start it only once, in the process that actually serves requests. ---
    if start_scheduler is None:
        start_scheduler = app.config["SCHEDULER_ENABLED"] and not app.config["TESTING"]
    in_reloader_parent = (not app.config["PRODUCTION"]) and os.environ.get("WERKZEUG_RUN_MAIN") != "true" and os.environ.get("RUNNING_VIA_SCRIPT") == "1"
    if start_scheduler and not in_reloader_parent:
        from services.reminder_service import start_scheduler as start
        start(app)
    return app


if __name__ == "__main__":
    os.environ["RUNNING_VIA_SCRIPT"] = "1"  # tells create_app that the Flask debug reloader may start a second process
    debug = not Config.PRODUCTION
    create_app().run(host="127.0.0.1", port=5000, debug=debug)
