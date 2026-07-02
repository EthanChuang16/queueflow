from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse
from app.tasks.job_tasks import process_csv
from prometheus_client import Counter


router = APIRouter()

SUPPORTED_JOB_TYPES = {"csv"}

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