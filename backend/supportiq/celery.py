"""Celery application bootstrap for SupportIQ."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "supportiq.settings")

app = Celery("supportiq")
# All Celery config lives under the CELERY_ namespace in Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")  # noqa: T201
