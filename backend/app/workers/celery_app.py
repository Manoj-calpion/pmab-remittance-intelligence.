"""Celery worker entrypoint.

The API runs jobs inline unless USE_CELERY=true. A failed broker is not
replaced with a successful inline result.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("pmab", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True)


@celery_app.task(name="pmab.process_ingestion")
def process_ingestion_task(directory: str, source_system: str) -> dict:
    from pathlib import Path

    from app.alerts.service import sync_alerts
    from app.core.database import get_session_factory
    from app.ingestion.pipeline import ingest_directory
    from app.models import ProcessingJob
    from app.models.base import utcnow

    db = get_session_factory()()
    job = ProcessingJob(job_type="directory_ingest", status="running", started_at=utcnow(), triggered_by="celery")
    db.add(job)
    db.commit()
    try:
        stats = ingest_directory(db, Path(directory), source_system, job.id)
        sync_alerts(db)
        job.status = "completed"
        job.stats = stats
    except Exception as exc:
        job.status = "failed"
        job.error_summary = str(exc)[:500]
        raise
    finally:
        job.finished_at = utcnow()
        db.commit()
        db.close()
    return stats
