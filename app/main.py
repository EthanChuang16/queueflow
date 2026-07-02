from fastapi import FastAPI
from app.api.jobs import router as jobs_router
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="QueueFlow",
    description="Async job processing system",
    version="0.1.0",
)

app.include_router(jobs_router, prefix="/api/v1")


# instrument the app and expose /metrics endpoint
Instrumentator().instrument(app).expose(app)

@app.get("/health")
def health_check():
    """Return service health status."""
    return {"status": "ok"}