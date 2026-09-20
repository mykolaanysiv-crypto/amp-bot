# АМП XP / «АМПасадори» v1.17.2 — Privacy & Data Integrity 2.0

## 1. Field-level encryption

Додано `app/field_crypto.py` і SQLAlchemy `EncryptedText`. Шифруються найбільш чутливі текстові поля профілю: vulnerability categories, restoration answers, block/deletion/rejection reasons. Формат ciphertext має version/key-id prefix, тому rotation підтримує кілька ключів на перехідний період.

Alembic `20260920_0010_privacy_data_integrity.py` не змінює PostgreSQL type (залишається TEXT), але backfill-шифрує вже існуючі plaintext values.

## 2. Secret rotation

- current: `FIELD_ENCRYPTION_KEY`;
- fallback: `WEB_SESSION_SECRET`;
- transition keyring: `FIELD_ENCRYPTION_PREVIOUS_KEYS`;
- re-encryption: `python -m scripts.rotate_field_encryption`.

Після успішної rotation старий ключ потрібно прибрати з previous keys.

## 3. Retention policy

Нові runtime rules:
- `privacy.registration_draft_days = 30`;
- `privacy.completed_journey_days = 180`;
- `privacy.session_history_days = 30`;
- `privacy.service_records_days = 180`;
- `privacy.temp_files_days = 7`.

Щоденний scheduler очищує тільки transient/service data. Не видаляються users, XP transactions, event registrations/attendance, audit logs, consent history.

## 4. Sensitive access audit

- sensitive profile view вже журналюється окремо;
- `/media`, `/uploads`, `/private` розрізняють view і download;
- parental consent document має окремі `web_sensitive_document_view` / `web_sensitive_document_download`.

## 5. Data Integrity Center

`/admin/data-integrity` — лише superadmin. Перевіряє:
- duplicate phones/email/profile (ПІБ + birth date);
- orphan XP/event registrations/reward claims;
- wallet > lifetime XP або negative wallet;
- inconsistent reward claims;
- invalid event registration statuses;
- attendance timestamp/status anomalies та future attendance;
- expired waitlist reservations;
- missing DB/local media.

Небезпечного auto-fix немає. Є лише ручні explicit дії, наприклад refresh event lifecycle і retention cleanup.

## 6. Real backup restore verification

`.github/workflows/backup.yml` після Heroku PGBackup:
1. отримує signed backup URL;
2. завантажує dump у ephemeral GitHub runner;
3. restore через `pg_restore` в ізольований PostgreSQL 16 service;
4. перевіряє мінімальну schema sanity, `users`, `alembic_version`;
5. лише після PASS записує `restore-verified` marker в AMP.

Pre-deploy capture більше не ставить false-positive verification marker без restore.

## 7. QA

- `python -m compileall -q app scripts tests migrations` — PASS;
- `python -m scripts.production_preflight` — PASS;
- Jinja parse: 57/57 — PASS;
- focused Privacy/Data Integrity + legacy regression source tests — PASS;
- повний runtime pytest у build container не запускався через відсутні `aiogram`/`aiosqlite`; authoritative full gate — локальне venv користувача та GitHub Actions/PostgreSQL 16.

Expected Alembic head: `20260920_0010`.
