"""SupportIQ Django project package."""
# Import the Celery app so `celery -A supportiq` and autodiscovery work.
from .celery import app as celery_app

__all__ = ("celery_app",)
