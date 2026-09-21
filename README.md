# AMP XP / «АМПасадори» v1.17.2.4 — Quest Proofs, Event End Time & Live Sync

v1.17.2.4 додає optional photo-proof flow для квестів, ручне підтвердження квесту суперадміном, явний час завершення події, налаштовувані вікна відмітки, feedback через 10 хв після `ends_at` та live-sync операційних блоків вебпанелі без повного перезавантаження. Alembic head — `20260921_0013`.

# AMP XP / «АМПасадори» v1.17.2.1 — Privacy & Data Integrity 2.0 + Duplicate Management

v1.17.2.1 зберігає Privacy & Data Integrity 2.0 та додатково дозволяє суперадміністратору безпечно керувати дублікатами і статусами. Базовий v1.17.2 посилює захист чутливих профільних даних і додає окремий **Data Integrity Center** для суперадміністратора. Реліз не виконує небезпечного автоматичного «виправлення» профілів, XP чи attendance: система знаходить аномалії, показує контекст і залишає рішення людині.

## Головне

- field-level encryption для найбільш чутливих TEXT-полів профілю через `EncryptedText` + Fernet;
- поточний ключ: `FIELD_ENCRYPTION_KEY`, fallback — `WEB_SESSION_SECRET`;
- підтримка попередніх ключів через `FIELD_ENCRYPTION_PREVIOUS_KEYS` і `scripts.rotate_field_encryption`;
- Alembic head: `20260920_0010` — existing plaintext sensitive fields backfill-шифруються під час migration;
- retention policy для registration drafts/journeys, завершених web-сесій, службових delivery-records і тимчасових файлів;
- щоденний `privacy_retention_scheduler` + ручний запуск із Data Integrity Center;
- окремий аудит sensitive profile view, sensitive media view/download та consent document view/download;
- Data Integrity Center: duplicate profile/phone/email, orphan records, XP/wallet/reward anomalies, attendance/status anomalies, expired reservations, missing media;
- реальна backup verification: Heroku PGBackup відновлюється в ephemeral PostgreSQL 16 у GitHub Actions і marker ставиться лише після успішного `pg_restore` + schema check.

## Важливі інваріанти

1. Схема production змінюється тільки Alembic.
2. Data Integrity Center доступний лише `superadmin`.
3. Автоматичний retention cleanup не видаляє профілі, XP history, attendance history, consent history або audit logs.
4. Дублікати профілів та orphan records не зливаються/не видаляються автоматично.
5. `FIELD_ENCRYPTION_PREVIOUS_KEYS` потрібен лише під час rotation і має бути видалений після успішної re-encryption.

## Після deploy

- `alembic current` → `20260920_0010 (head)`;
- `/health/ready` → HTTP 200;
- `/admin/data-integrity` → доступний суперадміну;
- GitHub workflow **AMP Verified Backup** має пройти `Capture + real restore verification`.
