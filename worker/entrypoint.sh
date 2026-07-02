#!/bin/sh
set -e

CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-4}"

exec celery -A app.core.celery.celery_app worker \
    --loglevel=info \
    --concurrency="${CELERY_CONCURRENCY}"
