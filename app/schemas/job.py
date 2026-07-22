from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobCreate(BaseModel):
    """What the client sends when submitting a job."""

    job_type: str
    payload: Optional[dict] = None


class JobResponse(BaseModel):
    """What the API returns for job status/result queries."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    job_type: str
    payload: Optional[dict] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime
