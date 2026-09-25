#!/usr/bin/env bash
set -euo pipefail

APP="${1:-${HEROKU_APP_NAME:-${HEROKU_APP:-amp-bot-ver-1-5-0}}}"
TARGET_URL="${RESTORE_DATABASE_URL:-}"

if [[ "${AMP_ALLOW_TEMP_RESTORE:-0}" != "1" ]]; then
  echo "Refusing restore: set AMP_ALLOW_TEMP_RESTORE=1 for an isolated temporary database." >&2
  exit 2
fi
if [[ -z "$TARGET_URL" ]]; then
  echo "RESTORE_DATABASE_URL is required and must point to an isolated temporary PostgreSQL database." >&2
  exit 2
fi
if [[ "$TARGET_URL" == *"heroku"* || "$TARGET_URL" == *"amazonaws.com"* ]]; then
  echo "Refusing restore target that looks like a hosted/production database." >&2
  exit 2
fi

if [[ -z "${AMP_RESTORE_CONTAINER_ID:-}" ]]; then
  echo "AMP_RESTORE_CONTAINER_ID is required (GitHub PostgreSQL service container)." >&2
  exit 2
fi
if [[ "$TARGET_URL" != "postgresql://amp:amp@127.0.0.1:5432/amp_restore_verify" ]]; then
  echo "Refusing restore: target must be the isolated GitHub PostgreSQL verification database." >&2
  exit 2
fi

DUMP="$(mktemp -t amp-pgbackup-XXXXXX.dump)"
DUMP_IN_CONTAINER="/tmp/amp-pgbackup-verify-${GITHUB_RUN_ID:-local}-$$.dump"
trap 'rm -f "$DUMP"; docker exec "$AMP_RESTORE_CONTAINER_ID" rm -f "$DUMP_IN_CONTAINER" >/dev/null 2>&1 || true' EXIT

echo "[1/5] Resolving latest Heroku PGBackup URL..."
BACKUP_URL="$(heroku pg:backups:url -a "$APP")"
test -n "$BACKUP_URL"

echo "[2/5] Downloading encrypted transport backup into ephemeral runner storage..."
curl -fL --retry 3 --retry-delay 2 "$BACKUP_URL" -o "$DUMP"
test -s "$DUMP"

echo "[3/5] Restoring into isolated PostgreSQL verification database..."
docker cp "$DUMP" "$AMP_RESTORE_CONTAINER_ID:$DUMP_IN_CONTAINER"
docker exec "$AMP_RESTORE_CONTAINER_ID" pg_restore --version
docker exec -e PGPASSWORD=amp "$AMP_RESTORE_CONTAINER_ID" \
  pg_restore --no-owner --no-acl --clean --if-exists --exit-on-error \
  -h 127.0.0.1 -U amp -d amp_restore_verify "$DUMP_IN_CONTAINER"

echo "[4/5] Validating restored schema and core tables..."
TABLE_COUNT="$(docker exec -e PGPASSWORD=amp "$AMP_RESTORE_CONTAINER_ID" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U amp -d amp_restore_verify -Atc "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE';")"
USER_TABLE="$(docker exec -e PGPASSWORD=amp "$AMP_RESTORE_CONTAINER_ID" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U amp -d amp_restore_verify -Atc "select count(*) from information_schema.tables where table_schema='public' and table_name='users';")"
ALEMBIC_TABLE="$(docker exec -e PGPASSWORD=amp "$AMP_RESTORE_CONTAINER_ID" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U amp -d amp_restore_verify -Atc "select count(*) from information_schema.tables where table_schema='public' and table_name='alembic_version';")"
if [[ "${TABLE_COUNT:-0}" -lt 20 || "$USER_TABLE" != "1" || "$ALEMBIC_TABLE" != "1" ]]; then
  echo "Restore verification failed: tables=$TABLE_COUNT users_table=$USER_TABLE alembic_table=$ALEMBIC_TABLE" >&2
  exit 1
fi
REVISION="$(docker exec -e PGPASSWORD=amp "$AMP_RESTORE_CONTAINER_ID" psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U amp -d amp_restore_verify -Atc "select version_num from alembic_version limit 1;")"
test -n "$REVISION"

echo "[5/5] Restore verified: tables=$TABLE_COUNT alembic=$REVISION"
echo "✅ Backup restore verification PASS"
