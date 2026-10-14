# SupportIQ Runbook

How to detect, diagnose, and recover from the failure modes this system
actually has. Every drill below describes **expected behavior first** — what
"healthy degradation" looks like — so on-call isn't guessing.

## Service map

| Service | Role | Health signal |
|---|---|---|
| `api` | Django + uvicorn, port 8000 | `GET /api/health/` → 200 `{"status":"ok","db":true}` |
| `worker` | Celery ingestion worker | `celery -A supportiq inspect ping` |
| `db` | Postgres 16 + pgvector | compose healthcheck (`pg_isready`) |
| `redis` | Broker + cache + rate-limit counters | compose healthcheck (`redis-cli ping`) |
| `frontend` | nginx serving the Vite build | `GET /` → 200 |

Logs are structured JSON on stdout (`docker compose logs api`); traces go to
the OTLP endpoint when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

---

## Drill 1 — Redis is down (TESTED)

**Blast radius:** Celery broker, semantic cache, rate-limit counters, token
budget counters, ingestion locks.

**Expected behavior (by design):**
- Chat **never 500s**. Every cache access is wrapped: failures degrade instead
  of raising.
- Token budgets are **fail-closed**: with the counter unreachable, `/ask`
  returns a structured SSE error event
  `{"type":"error","code":"budget_exceeded","detail":"token budget service unavailable"}`
  — an unbounded LLM bill is the worse failure mode.
- Rate limits are **fail-open** (logged loudly as `rate limiter degraded`).
  Availability over strictness here; budgets already guard cost.
- New uploads return 202 but ingestion **queues pile up** until Redis returns
  (Celery retries broker connection). Already-ingested KBs keep answering
  from Postgres.

**Detect:** `docker compose ps` (redis unhealthy), `budget_exceeded` error
events in chat, `cache read failed (degraded, continuing)` in API logs.

**Recover:** `docker compose restart redis` (or fix the underlying issue).
Queued ingestion jobs drain automatically. Verify: `redis-cli ping` → PONG,
then ask a question and confirm a `done` event.

**Automated test:** `backend/chat/tests/test_chat.py::TestChat::test_chat_survives_cache_outage`
simulates a dead cache backend and asserts: HTTP 200, no 500, structured
`budget_exceeded` error event with a human-readable `detail`.

---

## Drill 2 — Ingestion worker failure (partially tested)

**Symptoms:** document stuck in `processing`, or flipped to `failed` with an
`error` message visible in the Admin UI and `GET /api/kb/documents/`.

**What the system already does:**
- Transient infra errors (Redis/DB blips) hit Celery `autoretry_for`:
  3 retries with backoff before the task is marked failed.
- The task is **idempotent**: re-running it on a `ready` document is a no-op;
  a distributed lock (`ingest-lock:<id>`) prevents two workers ingesting the
  same document concurrently (double-click upload, broker redelivery).
- Failed ingestion deletes partial chunks atomically — readers never see half
  a document.

**Recover:**
1. Check the worker: `docker compose logs worker | tail -50`.
2. Fix the cause (bad PDF? out-of-memory on huge files?).
3. Re-queue: `POST /api/kb/documents/<id>/reingest/` (or the Admin UI retry).
4. Confirm the document reaches `ready` and `chunk_count > 0`.

**Automated tests:** `test_rerun_of_ready_document_is_noop`,
`test_concurrent_ingestion_single_flight`, `test_empty_file_marks_failed_with_error`
in `backend/kb/tests/test_ingestion.py`.

---

## Drill 3 — Postgres is down

**Symptoms:** `/api/health/` → 503 `{"status":"degraded","db":false}`;
API 500s on DB-backed endpoints (this one is NOT masked — without the
database there is nothing to serve).

**Recover:** `docker compose restart db`; data persists in the `pgdata`
volume. Verify `/api/health/` returns 200 before declaring recovery.

**Prevention:** the compose volume is the backup story for this project.
Production would add `pg_dump` cron + point-in-time recovery — noted as a
follow-up, not implemented.

---

## Useful commands

```bash
# Tail structured logs
docker compose logs -f api worker

# Where is a tenant's spend?
# GET /api/chat/budget/  (per-tenant, authenticated)

# Manually re-run evals after a retrieval change
docker compose exec api python -m pytest evals -q -s

# Measure cache latency honestly
docker compose exec api python manage.py benchmark_cache \
  --tenant acme --kb 1 --question "What is the refund policy?"

# Rotate the Django secret (then restart api + worker)
# 1. set DJANGO_SECRET_KEY in .env   2. docker compose up -d api worker
# Note: rotation invalidates all outstanding JWTs (by design).
```

## Known limitations (honest)

- SQLite dev mode has **no RLS** and brute-force vector search — correct for
  dev/test, not for production. The RLS tests only run on Postgres (CI).
- The deterministic stub providers make evals reproducible but say nothing
  about real-LLM answer quality; re-run `pytest evals/` after switching
  `LLM_BACKEND=gemini` and treat the thresholds as a starting point.
- Single Celery worker concurrency in compose (`--concurrency=2`); scale with
  `docker compose up --scale worker=3` for real load.
