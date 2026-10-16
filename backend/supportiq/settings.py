"""Django settings for SupportIQ.

Everything environment-specific comes from env vars (see .env.example).
Defaults are chosen so `python manage.py runserver` works with zero setup
(SQLite + in-process Celery eager mode + deterministic fake providers).
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Load a sibling .env file (repo root) into os.environ, without
    overriding variables the user already exported (explicit > file).

    This is intentionally tiny (no python-dotenv dependency): only plain
    KEY=VALUE lines are honored; comments and empty lines are skipped."""
    dotenv_path = BASE_DIR.parent / ".env"
    if not dotenv_path.is_file():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key")
DEBUG = env("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "tenants",
    "accounts",
    "kb",
    "chat",
]

MIDDLEWARE = [
    "supportiq.middleware.cors_middleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tenants.middleware.TenantMiddleware",  # resolves tenant AFTER auth
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "supportiq.urls"
WSGI_APPLICATION = "supportiq.wsgi.application"
ASGI_APPLICATION = "supportiq.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# ---------------------------------------------------------------- database
DATABASE_URL = env("DATABASE_URL", "")
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    _u = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _u.path.lstrip("/"),
            "USER": _u.username,
            "PASSWORD": _u.password,
            "HOST": _u.hostname,
            "PORT": _u.port or 5432,
            "OPTIONS": {"options": "-c statement_timeout=10000"},
        }
    }
    IS_POSTGRES = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
    IS_POSTGRES = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# ------------------------------------------------------------------ cache
REDIS_URL = env("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    # Local/dev fallback: in-memory. NOT shared across processes — fine for
    # dev, wrong for prod (compose always sets REDIS_URL).
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ------------------------------------------------------------------ celery
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = ("pytest" in sys.modules) or not bool(REDIS_URL)
# ^ eager under pytest (hermetic tests: ingestion runs inline), eager locally
# without Redis, real workers in compose.
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# --------------------------------------------------------------------- DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "TOKEN_OBTAIN_SERIALIZER": "accounts.serializers.TenantTokenObtainPairSerializer",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SupportIQ API",
    "DESCRIPTION": "Multi-tenant AI support agent platform.",
    "VERSION": "1.0.0",
}

# ------------------------------------------------------- supportiq toggles
LLM_BACKEND = env("LLM_BACKEND", "fake")  # "fake" | "gemini"
GEMINI_API_KEY = env("GEMINI_API_KEY", "")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-2.0-flash")

EMBEDDING_BACKEND = env("EMBEDDING_BACKEND", "deterministic")  # | "sentence-transformers"
EMBEDDING_DIM = env_int("EMBEDDING_DIM", 384)
SENTENCE_TRANSFORMER_MODEL = env("SENTENCE_TRANSFORMER_MODEL", "all-MiniLM-L6-v2")

RERANKER_BACKEND = env("RERANKER_BACKEND", "heuristic")  # | "cross-encoder"

ABSTAIN_THRESHOLD = env_float("ABSTAIN_THRESHOLD", 0.35)
# Semantic-only matches (zero shared content terms with the question) must
# clear this higher bar: with heuristic scoring there is no reliable synonym
# signal, so embedding-only evidence is treated as weak.
ABSTAIN_SEMANTIC_ONLY_THRESHOLD = env_float("ABSTAIN_SEMANTIC_ONLY_THRESHOLD", 0.55)
RETRIEVAL_TOP_K = env_int("RETRIEVAL_TOP_K", 5)

RATE_LIMIT_PER_USER = env_int("RATE_LIMIT_PER_USER", 30)
RATE_LIMIT_PER_TENANT = env_int("RATE_LIMIT_PER_TENANT", 300)
TOKEN_BUDGET_PER_TENANT = env_int("TOKEN_BUDGET_PER_TENANT", 1_000_000)

# ----------------------------------------------------------------- logging
LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            # Every log line carries these fields: timestamp, level, logger,
            # message, plus anything passed via extra={...}.
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "supportiq": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

# ---------------------------------------------------------- observability
# When OTEL_EXPORTER_OTLP_ENDPOINT is set (compose does this), traces are
# exported to the collector; otherwise the SDK stays a no-op.
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", "")

STATIC_URL = "static/"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20 MB knowledge-base uploads

# CORS - custom middleware (no extra dependency)
# Allows supportiq-client.vercel.app and all its preview deployments
