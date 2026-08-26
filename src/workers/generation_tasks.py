"""Generation worker tasks — run the agent pipeline for a task (§8.2)."""
from src.workers.celery_app import celery_app


@celery_app.task
def generate_content(task_id: str) -> dict:
    """Run the full LangGraph pipeline; persists drafts in REVIEW (§3.5)."""
    from src.agents import run_generation

    return run_generation(task_id)
