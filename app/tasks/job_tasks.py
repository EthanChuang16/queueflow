from app.core.celery import celery_app
from app.core.database import SessionLocal
from app.models.job import Job
import logging
import uuid
import time

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def process_csv(self, job_id: str):
    """simulates processing a csv job and updates the job status in postgres"""
    db = SessionLocal()
    job = None
    try:
        # fetch job from the db
        job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
        if not job:
            logger.error("process_csv: job %s not found, skipping", job_id)
            return

        # mark as processing
        job.status = "processing"
        db.commit()

        # simulate doing actual work
        time.sleep(2)

        # mark as completed with a result
        job.status = "completed"
        job.result = {"message": "CSV processed successfully", "rows": 100}
        db.commit()

    except Exception as exc:
        if job is not None:
            job.retry_count = (job.retry_count or 0) + 1
            if self.request.retries >= self.max_retries:
                job.status = "failed"
                job.error = str(exc)
            db.commit()

        if self.request.retries >= self.max_retries:
            logger.error("process_csv: job %s failed permanently: %s", job_id, exc)
            return

        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()