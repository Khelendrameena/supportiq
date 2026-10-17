"""ASGI entrypoint (used by uvicorn in docker-compose; nicer for SSE)."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "supportiq.settings")
application = get_asgi_application()
