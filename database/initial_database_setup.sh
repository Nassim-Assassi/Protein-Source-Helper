#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
ENV_FILE="${1:-$PROJECT_DIR/.env}"
SCHEMA_FILE="$SCRIPT_DIR/schema.sql"
VIEWS_FILE="$SCRIPT_DIR/views.sql"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

: "${DATABASE_HOST:?DATABASE_HOST is required in an env file or environment}"
: "${DATABASE_PORT:?DATABASE_PORT is required in an env file or environment}"
: "${DATABASE_NAME:?DATABASE_NAME is required in an env file or environment}"
: "${DATABASE_USER:?DATABASE_USER is required in an env file or environment}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required in an env file or environment}"

PGPASSWORD=$DATABASE_PASSWORD
PGSSLMODE=prefer
export PGPASSWORD PGSSLMODE

psql \
  --host "$DATABASE_HOST" \
  --port "$DATABASE_PORT" \
  --username "$DATABASE_USER" \
  --dbname "$DATABASE_NAME" \
  --single-transaction \
  --set ON_ERROR_STOP=1 \
  --file "$SCHEMA_FILE" \
  --file "$VIEWS_FILE"