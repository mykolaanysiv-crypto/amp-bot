# Heroku deploy — АМП XP v1.10.4

1. Створіть резервну копію production PostgreSQL:
   `heroku pg:backups:capture -a amp-bot-ver-1-5-0`.
2. Розпакуйте `amp_bot_v1104.zip` у чисту директорію.
3. Встановіть залежності: `pip install -r requirements.txt`.
4. Перевірте чинні `BOT_TOKEN`, `DATABASE_URL`, `WEB_SESSION_SECRET`, `TIMEZONE=Europe/Kyiv`, `MEDIA_STORAGE=database`, `PUBLIC_BASE_URL`.
5. Для донатів задайте `DONATION_JAR_URL=https://send.monobank.ua/jar/5S531LWQuc`; для автоматичної синхронізації — секретний `MONOBANK_TOKEN`.
6. Виконайте `python -m compileall -q app scripts tests` і `pytest -q`.
7. Перевірте `VERSION.txt = 1.10.4`.
8. Підключіть Heroku remote: `heroku git:remote -a amp-bot-ver-1-5-0`.
9. Якщо реліз розпаковано як чистий Git-репозиторій і історія Heroku відрізняється, після backup використайте `git push heroku HEAD:main --force`.
10. Startup виконає additive/idempotent schema upgrade до 52 таблиць; наявні учасники, XP, події та історія не очищаються.
11. `/health` має показати `1.10.4`.
12. Виконайте перевірки із `SERVER_UPDATE_V1104.md`.

Повні команди: `COMMANDS_V1104.txt`.
