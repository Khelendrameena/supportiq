#!/bin/bash
exec uvicorn supportiq.asgi:application --host 0.0.0.0 --port ${PORT:-8000}
