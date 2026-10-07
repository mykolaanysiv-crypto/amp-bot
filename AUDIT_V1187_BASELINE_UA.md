# Технічний аудит перед AMP XP v1.18.7

Дата: 07.10.2026

## Джерело істини
Для v1.18.7 використано **лише** `amp_bot_v1186_release_git.zip` — найновіший наданий архів із post-v1.18.6 hotfix. SHA256 source archive: `d8c86cff18b2daa285ed14946525f894929f9f0e8b82995b98b66d4b590e34cb`. Робочий Git HEAD усередині архіву: `7188d8a` (`hotfix/v1.18.6-heroku-url`). Старіший `amp_bot_v1186(1).zip` не використовувався як база, оскільки в ньому ще були старі `postgres:18` Docker Hub refs, `cryptography<47` та застарілий Heroku URL resolver.

## Поточний стан до змін
- APP_VERSION / VERSION: `1.18.6`.
- Alembic head: `20260925_0015`.
- Нової незастосованої міграції в source artifact не виявлено.
- Python target: `3.13`.
- CI/restore PostgreSQL: `18` через `public.ecr.aws/docker/library/postgres:18`.
- Dockerfile: Python 3.13.
- Local `docker-compose.yml`: PostgreSQL 16 — **версійний drift** від production/CI baseline.
- 266 Python-файлів у `app + scripts + tests + migrations`, близько 42.4 тис. рядків Python.
- 61 Jinja2 template, 15 Alembic revisions, 72 Python test files + 1 JS smoke test.

## Сильні production-механізми, які потрібно зберегти
- Alembic-only production schema ownership.
- Fresh Heroku PGBackup перед deploy + реальне restore verification на PostgreSQL 18.
- Post-deploy `/health/ready`, `/health/live`, version smoke.
- Окремий production `FIELD_ENCRYPTION_KEY`, previous-key rotation bridge.
- Server-side upload/request-size protection.
- Orphan `MediaAsset` detection у Data Integrity Center.
- Idempotent XP/attendance boundaries, granular permissions, privacy suppression, audit trail.

## Критичні/важливі знахідки
1. **Немає dependency lock.** `requirements.txt` містив діапазони, тому одна й та сама версія коду могла встановити інший набір direct dependencies пізніше.
2. **`pip-audit` був advisory.** У CI стояв `continue-on-error: true`, тобто відома dependency vulnerability не блокувала release. Для security baseline це неприйнятно.
3. **Local PostgreSQL drift.** `docker-compose.yml` використовував PostgreSQL 16, тоді як CI/backup verification — PostgreSQL 18.
4. **Release/docs consistency не автоматизована повністю.** VERSION/cache source gates існували, але README/HEROKU/manifest/lock fingerprints не були єдиним автоматичним контрактом.
5. **Безпечні deprecation warnings.** У тестах залишались `datetime.utcnow()` та deprecated openpyxl style copy; `alembic.ini` не мав `path_separator=os`.
6. **GitHub Actions major upgrades очікують Dependabot PR.** Їх не слід змішувати з reproducibility baseline без окремого CI-only validation.

## Рішення v1.18.7
- Не змінювати production schema або бізнес-семантику.
- Додати exact direct production/dev locks та автоматичний consistency gate.
- Зробити `pip-audit` blocking.
- Вирівняти local PostgreSQL baseline на 18.
- Додати release/documentation gate і build manifest fingerprints.
- Прибрати тільки безпечні deprecation warnings.
- Зберегти всі v1.18.6 security/reliability controls.

## Ризик релізу
Низький/середній: runtime/business code практично не змінюється; основний ризик — нові exact dependency pins. Саме тому clean install, `pip-audit`, full pytest та PostgreSQL integration **обов'язково мають пройти в GitHub Actions** перед merge/deploy. У локальному offline build environment ці checks не можна чесно вважати виконаними.
