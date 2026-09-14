# Команди та QR — поточний реліз v1.10.3

Актуальна повна інструкція deployment: **`COMMANDS_V1102.txt`**.

У v1.10.3 QR protocol збережений, але всі event check-in/attendance канали додатково захищені часовим window: за замовчуванням 60 хв до старту — 360 хв після. Поза window звичайне зарахування/XP заблоковане; web override вимагає причину та audit.

Перед deploy: backup PostgreSQL → rsync без `.git/.env/.venv/data` → dependencies → `compileall` → targeted tests → **повний `pytest -q`** → commit → `git push heroku main` → `/health` та logs.
