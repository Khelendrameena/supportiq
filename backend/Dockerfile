# Backend image: Django API + Celery worker (command selects the role).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg needs libpq at runtime (binary wheel bundles it; keep image slim).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY backend /app

EXPOSE 8000

# Default: run the API. docker-compose overrides the command for the worker.
CMD ["uvicorn", "supportiq.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
