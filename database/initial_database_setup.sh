#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$PROJECT_DIR/.env"
SCHEMA_FILE="$SCRIPT_DIR/schema.sql"

if [ ! -f "$ENV_FILE" ]; then
  printf 'Missing environment file: %s\n' "$ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a

: "${DATABASE_HOST:?DATABASE_HOST is required in .env}"
: "${DATABASE_PORT:?DATABASE_PORT is required in .env}"
: "${DATABASE_NAME:?DATABASE_NAME is required in .env}"
: "${DATABASE_USER:?DATABASE_USER is required in .env}"
: "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required in .env}"

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
  --file "$SCHEMA_FILE"