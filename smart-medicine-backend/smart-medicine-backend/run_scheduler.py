"""Run the reminder scheduler as its OWN process (recommended for production).
Start the web server with SCHEDULER_ENABLED=false, and run this file once:   python run_scheduler.py
"""
from apscheduler.schedulers.blocking import BlockingScheduler

from app import create_app
from services.reminder_service import run_cycle

app = create_app(start_scheduler=False)
scheduler = BlockingScheduler()
scheduler.add_job(run_cycle, "interval", args=[app], seconds=app.config["SCHEDULER_INTERVAL_SECONDS"],
                  id="medicine_cycle", max_instances=1, coalesce=True)
print("Scheduler running. Press Ctrl+C to stop.")
try:
    scheduler.start()
except (KeyboardInterrupt, SystemExit):
    pass
