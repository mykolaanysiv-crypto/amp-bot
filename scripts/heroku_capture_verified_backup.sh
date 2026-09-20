#!/usr/bin/env bash
set -euo pipefail

APP="${1:-${HEROKU_APP:-amp-bot-ver-1-5-0}}"
LABEL="Heroku restore-verified PGBackup $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

echo "[1/3] Creating Heroku Postgres backup for ${APP}..."
heroku pg:backups:capture -a "${APP}"

echo "[2/3] Backup captured and listed by Heroku..."
heroku pg:backups -a "${APP}" | sed -n '1,14p'

if [[ -n "${RESTORE_DATABASE_URL:-}" && "${AMP_ALLOW_TEMP_RESTORE:-0}" == "1" ]]; then
  echo "[3/3] Restoring into isolated verification database..."
  ./scripts/verify_backup_restore.sh "${APP}"
  heroku run -a "${APP}" -- python -m scripts.mark_backup_verified "${LABEL}"
  heroku run -a "${APP}" -- python -m scripts.verify_backup_marker
  echo "✅ Backup capture + restore verification completed."
else
  echo "[3/3] Restore verification skipped: no isolated RESTORE_DATABASE_URL was provided."
  echo "ℹ️ Backup health marker was NOT updated. Use GitHub AMP Verified Backup workflow for real restore verification."
fi
