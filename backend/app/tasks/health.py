from app.worker import celery_app


@celery_app.task(name="app.tasks.health.ping", ignore_result=True)
def ping() -> dict[str, str]:
    """Harmless transport smoke task; returns locally, stores no result or business data."""
    return {"status": "ok", "service": "eduvia-worker"}
