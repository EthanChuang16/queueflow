from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse
from app.tasks.job_tasks import process_csv
from prometheus_client import Counter


router = APIRouter()

SUPPORTED_JOB_TYPES = {"csv"}
SUPPORTED_JOB_STATUSES = {"pending", "processing", "completed", "failed"}

# counts how many jobs have been submitted by type
jobs_submitted = Counter(
    "queueflow_jobs_submitted_total",
    "Total number of jobs submitted",
    ["job_type"]
)


@router.post("/jobs", response_model=JobResponse)
def submit_job(job_data: JobCreate, db: Session = Depends(get_db)):
    """Accept a job request, save it to the DB as pending, and return the job record."""
    if job_data.job_type not in SUPPORTED_JOB_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported job_type: {job_data.job_type!r}")

    job = Job(
        job_type=job_data.job_type,
        payload=job_data.payload,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    process_csv.delay(str(job.id))
    jobs_submitted.labels(job_type=job_data.job_type).inc()
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    """Fetch a job by ID and return its current status and result."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    List jobs with optional status filter.
    Examples:
        GET /api/v1/jobs?status=failed  - all permamently failed jobs
        GET /api/v1/jobs?status=pending - all pending jobs
        GET /api/v1/jobs                - all jobs (last 50)
    """
    if status is not None and status not in SUPPORTED_JOB_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported status: {status!r}")

    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()
    return jobs


@router.post("/jobs/{job_id}/requeue", response_model=JobResponse)
def requeue_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Requeue a permanently failed job for reprocessing.
    Resets status to pending and retry count to 0.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "failed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in failed state, current status: {job.status}"
        )

    job.status = "pending"
    job.retry_count = 0
    job.error = None
    db.commit()
    db.refresh(job)

    process_csv.delay(str(job.id))
    jobs_submitted.labels(job_type=job.job_type).inc()
    return job

