# AMP XP / «АМПасадори» v1.12.1.5 — Backup Verification Automation Hotfix

Цей hotfix прибирає false-positive повідомлення «Резервна копія потребує перевірки» одразу після першого запуску нового моніторингу та робить backup verification автоматичним.

## Що змінилось
1. Якщо в БД ще немає `last_backup_at`, worker створює `monitor.backup.unknown_since` і дає 24 години на першу автоматично підтверджену копію без Telegram alarm.
2. Після grace alarm знову працює, якщо копію так і не підтверджено. Stale/invalid backups не отримують grace.
3. Production CI перед deploy створює Heroku PGBackup, запускає `scripts.mark_backup_verified` і `scripts.verify_backup_marker`. Якщо backup не створився/не зафіксувався — deploy не починається.
4. `.github/workflows/backup.yml` щодня створює verified PGBackup; його також можна запустити вручну через Actions → AMP Verified Backup → Run workflow.
5. Web «Стан системи» розрізняє `перевірено`, `очікує першої автоматичної перевірки`, `копія застаріла`, `помилка маркера`, `ще не підтверджено`.

## Config
Опційно: `BACKUP_UNKNOWN_GRACE_HOURS=24` (1..168).

Схема БД не змінена.
