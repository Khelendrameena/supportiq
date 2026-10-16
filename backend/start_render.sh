#!/bin/bash
# Start Celery worker in background, then run API in foreground
# (migrations run separately to isolate failures)
celery -A supportiq worker --loglevel=info --concurrency=1 &
exec uvicorn supportiq.asgi:application --host 0.0.0.0 --port ${PORT:-8000}
