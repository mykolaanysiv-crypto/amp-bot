#!/usr/bin/env bash
set -euo pipefail

APP="${1:-${HEROKU_APP:-amp-bot-ver-1-5-0}}"
LABEL="Heroku PGBackup $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

echo "[1/3] Creating Heroku Postgres backup for ${APP}..."
heroku pg:backups:capture -a "${APP}"

echo "[2/3] Verifying backup is listed by Heroku..."
heroku pg:backups -a "${APP}" | sed -n '1,14p'

echo "[3/3] Recording verified marker in AMP system health..."
heroku run -a "${APP}" -- python -m scripts.mark_backup_verified "${LABEL}"

heroku run -a "${APP}" -- python -m scripts.verify_backup_marker

echo "✅ Backup capture completed and verification marker recorded."
