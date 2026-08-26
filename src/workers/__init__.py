"""Background workers — Celery app and task modules (design doc §8).

Workers import services/agents; services never import workers at module
level (dispatch is lazy inside service functions).
"""
