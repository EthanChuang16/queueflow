from fastapi import FastAPI
from app.api.jobs import router as jobs_router

app = FastAPI(
    title="QueueFlow",
    description="Async job processing system",
    version="0.1.0",
)

app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "ok"}