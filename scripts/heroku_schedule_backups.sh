#!/bin/zsh
set -euo pipefail
APP="${1:-amp-bot-ver-1-5-0}"
TIME="${2:-03:00 Europe/Kyiv}"
echo "Налаштовую щоденний PGBackup для $APP о $TIME"
heroku pg:backups:schedule DATABASE_URL --at "$TIME" --app "$APP"
echo
echo "Поточний розклад:"
heroku pg:backups:schedules --app "$APP"
