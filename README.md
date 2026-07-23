# QueueFlow

[![CI](https://github.com/EthanChuang16/queueflow/actions/workflows/ci.yml/badge.svg)](https://github.com/EthanChuang16/queueflow/actions/workflows/ci.yml)

Async job processing system built around a simple pattern: an API accepts a job, drops it in a queue, and a separate worker pool executes it.
The job type in this build is CSV processing, but the point of the project is the API/queue/worker plumbing, not the CSV logic.
That layer is intentionally interchangeable.

## What it is

A client submits a job over HTTP.
The API writes a row to Postgres with status `pending` and pushes the job onto a Redis-backed Celery queue, then returns immediately with the job's ID.
A Celery worker, running as a separate process from a separate container, picks the job up, marks it `processing`, does the work, and writes back `completed` or `failed`.
The client polls `GET /api/v1/jobs/{id}` to check on it.

In this build, `process_csv` simulates the work: it sleeps for two seconds and writes back a fixed result (`{"message": "CSV processed successfully", "rows": 100}`).
It does not actually parse the uploaded file yet.
Failures retry up to 3 times with exponential backoff (5s base, capped at 60s).
Once retries are exhausted the job is marked `failed` with the error message attached, which is the dead letter behavior here: there is no separate dead letter queue, just a terminal status in Postgres that `POST /api/v1/jobs/{id}/requeue` can reset back to `pending`.

## Architecture

![Architecture diagram](docs/architecture.png)

*(diagram placeholder, add the real one at `docs/architecture.png`)*

```
Client → FastAPI → PostgreSQL (job row created, status: pending)
                 → Redis (job pushed onto the Celery queue)
                       ↓
              Celery Worker (picks up job, runs it)
                       ↓
               PostgreSQL (status updated: completed / failed)
```

The API and worker share the same codebase and the same `Job` model, they just run different entrypoints (`uvicorn` vs `celery worker`).
Prometheus scrapes `/metrics` from both processes.
Grafana reads from Prometheus.
Flower talks to Redis directly to show live Celery task state.

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, Uvicorn |
| Task queue | Celery |
| Broker and result backend | Redis |
| Database | PostgreSQL, SQLAlchemy ORM, Alembic migrations |
| Worker | Celery worker process, same codebase as the API, separate container |
| Metrics | prometheus-fastapi-instrumentator on the API, prometheus_client (multiprocess mode) on the worker |
| Dashboards | Grafana |
| Task monitoring | Flower |
| Containers | Docker, Docker Compose |
| Orchestration | Kubernetes, Helm |
| CI/CD | GitHub Actions, GHCR |
| Testing | Pytest, HTTPX, in-memory SQLite for the test DB |
| Lint and format | flake8, black, isort |

## Quick start (Docker Compose)

Requires Docker and Docker Compose. Nothing else needs to be installed on the host.

Clone the repo:

```bash
git clone git@github.com:EthanChuang16/queueflow.git
cd queueflow
```

Create a `.env` file in the project root. Docker Compose reads these values directly, nothing here is committed to the repo:

```bash
cat > .env <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
POSTGRES_DB=queueflow
SECRET_KEY=localsecretkey123
CELERY_CONCURRENCY=4
DEBUG=true
GRAFANA_ADMIN_PASSWORD=admin
EOF
```

Build and start everything:

```bash
docker compose up -d --build
```

This starts Postgres, Redis, the API, the worker, Flower, Prometheus, and Grafana.
The API and worker wait for Postgres and Redis to report healthy before starting.

Run the database migration, the `jobs` table does not exist until this runs:

```bash
docker compose exec api alembic upgrade head
```

Confirm the API is up:

```bash
curl http://localhost:8000/health
```

Submit a job:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "csv", "payload": {"filename": "sample.csv"}}'
```

Check its status with the ID from the response above:

```bash
curl http://localhost:8000/api/v1/jobs/<job_id>
```

It goes `pending` → `processing` → `completed` over a couple of seconds.

Services once the stack is up:

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Flower (Celery UI) | http://localhost:5555 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / the value of `GRAFANA_ADMIN_PASSWORD`) |

## Monitoring

![Grafana dashboard](docs/grafana.png)

*(screenshot placeholder, add the real one at `docs/grafana.png`)*

Grafana is provisioned on startup with a dashboard called "QueueFlow overview" reading from the Prometheus datasource, no manual setup needed.
It tracks:

- Job submission rate
- Job completion rate
- Job failure rate
- Job processing duration, p95

Prometheus scrapes `api:8000/metrics` and `worker:9090/metrics` every 15 seconds, see `monitoring/prometheus.yml`.
The worker's metrics port is separate from its Celery process, it runs a small WSGI server on `worker_init` specifically to aggregate per-process counters, since Celery's prefork pool forks the task code into child processes that don't share a metrics registry.

## API endpoints

All job endpoints live under `/api/v1`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/jobs` | Submit a job. Body: `{"job_type": "csv", "payload": {...}}`. Returns the job record with status `pending`. |
| GET | `/api/v1/jobs/{job_id}` | Fetch a single job by ID. |
| GET | `/api/v1/jobs` | List jobs, newest first. Optional `?status=` filter (`pending`, `processing`, `completed`, `failed`) and `?limit=` (default 50, max 200). |
| POST | `/api/v1/jobs/{job_id}/requeue` | Reset a `failed` job back to `pending` and dispatch it again. 400 if the job isn't currently `failed`. |
| GET | `/health` | Health check, returns `{"status": "ok"}`. |
| GET | `/metrics` | Prometheus metrics for the API process. |

`csv` is currently the only supported `job_type`, anything else returns a 400.

## Running tests

Tests run against an in-memory SQLite database and mock out the Celery dispatch, so no Docker, Postgres, or Redis is required:

```bash
pip install -r requirements.txt
pytest tests/ -v
```

Lint and format checks, the same ones CI runs:

```bash
flake8 app/ tests/
black --check app/ tests/
isort --check-only app/ tests/
```

There's also a small async load test script at `scripts/load_test.py` that fires 50 concurrent job submissions at a running API. Update the `API_URL` constant at the top of the file to match wherever your API is actually listening before running it.

## Kubernetes deployment

Two equivalent ways to deploy this, raw manifests under `k8s/` or the Helm chart under `helm/queueflow/`.

### Raw manifests

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/
```

This creates the `queueflow` namespace and deploys Postgres (with a PVC), Redis, the API (2 replicas, NodePort service), and the worker (2 replicas, no service since it only consumes from Redis).
A `HorizontalPodAutoscaler` scales the worker deployment between 1 and 10 replicas targeting 50% average CPU utilization.

The manifests default to `imagePullPolicy: Never` on images tagged `:latest`, which assumes the images already exist in the cluster's local Docker daemon, for example `minikube`. Build and load them before applying:

```bash
docker build -t queueflow-api:latest -f Dockerfile.api .
docker build -t queueflow-worker:latest -f Dockerfile.worker .
minikube image load queueflow-api:latest
minikube image load queueflow-worker:latest
```

### Helm chart

```bash
helm install queueflow helm/queueflow
```

Uses `values.yaml` by default, same local-image assumptions as the raw manifests above.
For staging or production, layer the corresponding values file on top, these point at the GHCR images and switch to `pullPolicy: Always`:

```bash
helm install queueflow helm/queueflow -f helm/queueflow/values.staging.yaml
helm install queueflow helm/queueflow -f helm/queueflow/values.production.yaml
```

Both files currently pin the image tag to `latest` with a TODO to switch to the git SHA the CI pipeline built, worth doing before pointing this at a real cluster.

One more thing worth knowing before using this against a real cluster: `helm/queueflow/templates/secret.yaml` and `k8s/secret.yaml` only base64-encode the DB password and secret key, they aren't encrypted. That's fine for a local or demo cluster, anyone with read access to Secrets in the namespace can decode them with `base64 -d`. Swap in sealed-secrets, external-secrets, or a vault-backed provider before this touches anything real.

## Project structure

```
queueflow/
├── app/
│   ├── api/              # FastAPI routes (jobs.py)
│   ├── core/             # Settings, DB session, Celery app config
│   ├── models/            # SQLAlchemy models (Job)
│   ├── schemas/           # Pydantic request/response schemas
│   ├── tasks/             # Celery task definitions (process_csv)
│   └── main.py            # FastAPI app entrypoint
├── worker/
│   └── entrypoint.sh       # Celery worker startup script
├── alembic/                # Database migrations
├── tests/                  # Pytest suite
├── scripts/
│   └── load_test.py        # Concurrent job submission load test
├── helm/queueflow/          # Helm chart (base + staging/production values)
├── k8s/                     # Raw Kubernetes manifests
├── monitoring/
│   ├── prometheus.yml       # Prometheus scrape config
│   └── grafana/provisioning # Auto-provisioned datasource + dashboard
├── .github/workflows/ci.yml # CI/CD pipeline
├── Dockerfile.api
├── Dockerfile.worker
├── docker-compose.yml
└── CLAUDE.md
```

## CI/CD

GitHub Actions runs on every push to `main` and every pull request into it, defined in `.github/workflows/ci.yml`.

The test job always runs: it spins up Postgres and Redis as service containers, then runs `flake8`, `black --check`, `isort --check-only`, and the full Pytest suite against them.

The build job runs only on push to `main`, and only after the test job passes.
It logs into GHCR, then builds and pushes both images with two tags each, `latest` and the commit SHA.
The repository owner is lowercased before tagging, since Docker registry paths must be lowercase and the GitHub username here isn't.

## Docker images on GHCR

```bash
docker pull ghcr.io/ethanchuang16/queueflow-api:latest
docker pull ghcr.io/ethanchuang16/queueflow-worker:latest
```

Both are also available tagged with the commit SHA they were built from, for pinning to a known-good build instead of floating `latest`.
