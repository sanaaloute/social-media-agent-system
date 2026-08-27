"""Local scheduler for standalone (eager-mode) operation (§8.1).

In Docker, Celery beat drives these loops; when running locally without a
broker there is no beat process, so this runner performs the same duties
in-process:

- every 60s: publish due scheduled content (dispatch_due)
- every 15 min: autopilot tick (discover → generate → auto-approve)

Run with:  python -m src.workers.local_scheduler
Stop with Ctrl+C. The web server must be running for the panel/API, but
this scheduler talks to the database directly and does not need it.
"""
import logging
import time
from datetime import datetime

from sqlmodel import Session

from src.core.database.engine import engine, init_db
from src.core.logging_setup import configure_logging
from src.services import schedule_service
from src.services.autopilot_service import autopilot_tick

logger = logging.getLogger(__name__)

DUE_INTERVAL_SEC = 60
AUTOPILOT_INTERVAL_SEC = 15 * 60


def run() -> None:
    configure_logging()
    init_db()
    logger.info(
        "local scheduler started (dispatch_due every %ds, autopilot every %ds)",
        DUE_INTERVAL_SEC,
        AUTOPILOT_INTERVAL_SEC,
    )
    last_autopilot = 0.0
    while True:
        started = time.monotonic()
        try:
            with Session(engine) as session:
                dispatched = schedule_service.dispatch_due(session)
                if dispatched:
                    logger.info("dispatched %d due posts", dispatched)
            if started - last_autopilot >= AUTOPILOT_INTERVAL_SEC:
                last_autopilot = started
                with Session(engine) as session:
                    summary = autopilot_tick(session)
                logger.info("autopilot tick: %s", summary)
        except Exception:
            logger.exception("scheduler loop error — continuing")
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, DUE_INTERVAL_SEC - elapsed))


if __name__ == "__main__":
    run()
