#!/bin/bash
set -e
python3 manage.py migrate --noinput
# Start Celery worker in background, then run API in foreground
celery -A supportiq worker --loglevel=info --concurrency=1 &
exec uvicorn supportiq.asgi:application --host 0.0.0.0 --port ${PORT:-8000}
