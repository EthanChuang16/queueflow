import logging
import os
import shutil
import threading
import time
import uuid
from wsgiref.simple_server import make_server

from celery.signals import worker_init, worker_process_shutdown
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    make_wsgi_app,
    multiprocess,
)

from app.core.celery import celery_app
from app.core.database import SessionLocal
from app.models.job import Job

logger = logging.getLogger(__name__)


@worker_init.connect
def _start_metrics_server(**kwargs):
    """Serve a multiprocess-aware /metrics endpoint once the worker's main
    process boots, before it forks the prefork pool.

    With CELERY_CONCURRENCY > 1, task code (and its .inc()/.observe() calls)
    runs in forked child processes, each with its own in-memory registry. A
    plain start_http_server() here would only ever expose the parent
    process's (always-empty) counters. Instead, PROMETHEUS_MULTIPROC_DIR
    (set in the container environment, required by prometheus_client before
    any Counter/Histogram is instantiated) makes each metric write its value
    to a per-process file; MultiProcessCollector merges those files across
    all live children on every scrape.

    Module-level execution would also fire in the API process (it imports
    process_csv for .delay()), colliding on port 9090 — hence gating this on
    worker_init instead.
    """
    multiproc_dir = os.environ["PROMETHEUS_MULTIPROC_DIR"]
    # Stale files from a previous run map to PIDs that no longer exist and
    # would double-count metrics if left in place.
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    httpd = make_server("0.0.0.0", 9090, make_wsgi_app(registry))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


@worker_process_shutdown.connect
def _cleanup_metrics(pid, **kwargs):
    """Drop a forked child's metric files when it exits, so a recycled or
    autoscaled pool doesn't accumulate stale/duplicate series over time."""
    multiprocess.mark_process_dead(pid)


# counts jobs that completed successfully by job type
jobs_completed = Counter(
    "queueflow_jobs_completed_total",
    "Total number of jobs completed successfully",
    ["job_type"],
)

# counts jobs that failed permanently by job type
jobs_failed = Counter(
    "queueflow_jobs_failed_total",
    "Total number of jobs that failed permanently",
    ["job_type"],
)

# tracks how long each job takes to process
job_duration = Histogram(
    "queueflow_job_processing_seconds",
    "Time spent processing jobs in seconds",
    ["job_type"],
)


@celery_app.task(
    bind=True, max_retries=3, retry_backoff=5, retry_backoff_max=60, retry_jitter=False
)
def process_csv(self, job_id: str):
    """Simulates processing a CSV job and updates the job status in Postgres."""
    db = SessionLocal()
    job = None
    start_time = time.time()

    try:
        job = db.query(Job).filter(Job.id == uuid.UUID(job_id)).first()
        if not job:
            logger.error("process_csv: job %s not found, skipping", job_id)
            return

        job.status = "processing"
        db.commit()

        # simulate doing actual work
        time.sleep(2)

        job.status = "completed"
        job.result = {"message": "CSV processed successfully", "rows": 100}
        db.commit()

        # record successful completion metrics
        duration = time.time() - start_time
        jobs_completed.labels(job_type="csv").inc()
        job_duration.labels(job_type="csv").observe(duration)

    except Exception as exc:
        db.rollback()

        if job is not None:
            job.retry_count = (job.retry_count or 0) + 1
            if self.request.retries >= self.max_retries:
                job.status = "failed"
                job.error = str(exc)
                jobs_failed.labels(job_type="csv").inc()
            db.commit()

        if self.request.retries >= self.max_retries:
            logger.error("process_csv: job %s failed permanently: %s", job_id, exc)
            return

        raise self.retry(exc=exc)
    finally:
        db.close()
