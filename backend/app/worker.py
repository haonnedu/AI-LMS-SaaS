"""Celery transport only. Durable job state lives in PostgreSQL ``background_jobs``;
messages carry job IDs and the sweeper re-dispatches jobs whose message was lost."""

from celery import Celery
from kombu import Queue

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "eduvia",
    broker=settings.celery_broker_url.get_secret_value(),
    include=["app.tasks.health", "app.tasks.jobs"],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_ignore_result=True,
    task_default_queue="default",
    task_queues=tuple(
        Queue(name) for name in ("default", "ingestion", "generation", "export", "omr")
    ),
    task_routes={
        "app.tasks.health.ping": {"queue": "default"},
        "app.tasks.jobs.run": {"queue": "ingestion"},
        "app.tasks.jobs.sweep": {"queue": "default"},
    },
    # app.tasks.jobs.run sets acks_late/reject_on_worker_lost itself; PostgreSQL leases
    # decide whether a redelivered message may run. Beat runs only as its own process.
    beat_schedule={
        "sweep-overdue-jobs": {"task": "app.tasks.jobs.sweep", "schedule": 60.0},
    },
    task_create_missing_queues=False,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_transport_options={"visibility_timeout": 3600},
    task_soft_time_limit=60,
    task_time_limit=90,
    enable_utc=True,
    timezone="UTC",
)
