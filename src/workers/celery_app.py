"""Celery application (design doc §8.1).

Two queue modes (settings.queue_mode):
- ``eager``: tasks run synchronously in-process via ``.delay()`` — used for
  local dev and tests; no broker needed.
- ``celery``: a real Redis broker/backend; beat dispatches due scheduled
  content every 60 seconds via ``dispatch_due_task``.
"""
from celery import Celery

from src.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "social_agent",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or "cache+memory://",
    include=[
        "src.workers.generation_tasks",
        "src.workers.publish_tasks",
        "src.workers.autopilot_tasks",
    ],
)

if settings.queue_mode == "eager":
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)

celery_app.conf.beat_schedule = {
    "dispatch-due-content": {
        "task": "src.workers.publish_tasks.dispatch_due_task",
        "schedule": 60.0,
    },
    "autopilot-tick": {
        "task": "src.workers.autopilot_tasks.autopilot_tick_task",
        "schedule": 900.0,  # every 15 minutes
    },
}
