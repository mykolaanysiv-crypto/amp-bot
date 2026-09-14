# Heroku deploy — АМП XP v1.11.0

Поточний рекомендований сценарій — **оновлення поверх чинного Heroku commit без нового `git init` і без `--force`**.

1. Backup: `heroku pg:backups:capture -a amp-bot-ver-1-5-0`.
2. У чинному Git-репозиторії: `git fetch heroku main && git reset --hard heroku/main`.
3. Розпакуйте `amp_bot_v1110.zip` у `/tmp` і накладіть його через `rsync`, зберігаючи `.git`, `.env`, `.venv`.
4. Перевірте `VERSION.txt = 1.11.0` і що `.env` ігнорується Git.
5. Не змінюйте `WEB_SESSION_SECRET` під час звичайного update.
6. `MONOBANK_TOKEN` має залишатися тільки у Heroku Config Vars / захищеному локальному `.env`.
7. `git add -A && git commit -m "Upgrade AMP to v1.11.0"`.
8. `git push heroku HEAD:main`.
9. Startup/release phase виконає additive/idempotent schema upgrade до **53 таблиць**.
10. Перевірте `/health = 1.11.0`, Registration UX, Feedback 2.0, Operations Dashboard і Monobank sync.

Повна інструкція: `SERVER_UPDATE_V1110.md`.
Команди одним блоком: `COMMANDS_V1110.txt`.
