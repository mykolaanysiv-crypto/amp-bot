АМПасадори v1.18.3 — виправлення двох груп помилок тестування.

1. app/version.py: резервна версія 1.18.3 (замість 1.18.2).
2. migrations/versions/20260925_0015_quest_qr_on_time.py: Alembic batch mode
   для SQLite, збереження зовнішнього ключа events.id і підтримка PostgreSQL.

Встановити на Mac у корені репозиторію:
  mkdir -p ~/Downloads/amp_v1183_testfix_unpack
  unzip -oq ~/Downloads/amp_bot_v1183_testfix.zip -d ~/Downloads/amp_v1183_testfix_unpack
  rsync -av ~/Downloads/amp_v1183_testfix_unpack/amp_bot_v1183_testfix/ ./

Після встановлення запустити:
  python -m pytest -q tests/test_v11303_telegram_web_ux_hotfix.py::test_v11303_version_is_synchronized tests/test_v11304_ci_localization_time_hotfix.py::test_v11304_version_and_cache_tokens_are_synchronized
  python -m pytest -q tests/test_v1182_qr_quests.py
  python -m pytest -q --ignore=tests/integration
  git diff --check

Не оновлювати production до успішного GitHub CI та перевіреного PGBackup.
