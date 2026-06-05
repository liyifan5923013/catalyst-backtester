#!/bin/sh
# Container entrypoint: run DB migrations when a persistence backend is
# configured, then launch the API server. With no DATABASE_URL (e.g. the
# zero-ops HF demo) migrations are skipped and the app uses the parquet cache.
set -e

if [ -n "$DATABASE_URL" ]; then
  echo "DATABASE_URL set -> running alembic migrations"
  alembic upgrade head
else
  echo "DATABASE_URL unset -> skipping migrations (parquet fallback)"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}"
