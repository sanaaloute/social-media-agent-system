"""Uniform logging configuration for web and worker processes (§6).

Every entry point (uvicorn lifespan, Celery worker) calls this once so
pipeline node logs, retries, and adapter errors look identical everywhere.
"""
import logging

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=_FORMAT, force=True)
    # Noisy third parties down to WARNING; our modules stay at INFO.
    for noisy in ("httpx", "httpcore", "kombu", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
