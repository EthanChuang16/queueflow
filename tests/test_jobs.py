import pytest
from unittest.mock import patch

# ---- POST /jobs tests ----

@pytest.fixture(autouse=True)
def mock_celery_delay():
    """Prevent tests from actually dispatching to Celery/Redis."""
    with patch("app.api.jobs.process_csv.delay") as mock_delay:
        yield mock_delay

def test_submit_job_returns_pending(client):
    """
    Submitting a valid job should immediately return
    a job record with status pending.
    """
    response = client.post("/api/v1/jobs", json={
        "job_type": "csv",
        "payload": {"filename": "test.csv"}
    })

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["job_type"] == "csv"
    assert data["payload"] == {"filename": "test.csv"}
    assert "id" in data
    assert "created_at" in data

def test_submit_job_invalid_type_returns_400(client, mock_celery_delay):
    """
    Submitting an unsupported job type should be
    rejected with a 400 before touching the database.
    """
    response = client.post("/api/v1/jobs", json={
        "job_type": "banana",
        "payload": {}
    })

    assert response.status_code == 400
    assert "Unsupported job_type" in response.json()["detail"]
    mock_celery_delay.assert_not_called()

def test_submit_job_missing_job_type_returns_422(client):
    """
    Submitting a request with no job_type should
    be rejected by Pydantic validation with a 422.
    """
    response = client.post("/api/v1/jobs", json={
        "payload": {"filename": "test.csv"}
    })

    assert response.status_code == 422

def test_submit_job_dispatches_celery_task(client, mock_celery_delay):
    """
    Submitting a valid job should call process_csv.delay
    exactly once with the job's ID.
    """
    response = client.post("/api/v1/jobs", json={
        "job_type": "csv",
        "payload": {"filename": "test.csv"}
    })

    job_id = response.json()["id"]
    mock_celery_delay.assert_called_once_with(job_id)

# ---- GET /jobs/{job_id} tests ----

def test_get_job_returns_correct_record(client):
    """
    Fetching a job by ID should return that exact job record.
    """
    post_response = client.post("/api/v1/jobs", json={
        "job_type": "csv",
        "payload": {"filename": "test.csv"}
    })

    job_id = post_response.json()["id"]
    response = client.get(f"/api/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["status"] == "pending"

def test_get_job_not_found_returns_404(client):
    """
    Fetching a job ID that doesn't exist should return 404.
    """
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/jobs/{fake_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"

def test_get_job_invalid_uuid_returns_422(client):
    """
    Fetching with a malformed UUID should be rejected
    by FastAPI before hitting the database.
    """
    response = client.get("/api/v1/jobs/not-a-valid-uuid")
    assert response.status_code == 422