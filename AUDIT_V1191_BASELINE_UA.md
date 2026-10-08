# Аудит бази перед AMP XP v1.19.1

Джерело істини: наданий користувачем `amp_bot_v1190_production_final.zip`.

- Базова версія: 1.19.0.
- Python: 3.13.
- PostgreSQL production/integration baseline: 18.
- Alembic head до змін: 20261007_0016.
- Alembic head v1.19.1: 20261008_0017.
- MediaAsset до v1.19.1 зберігав category, filename, content_type, binary data, size_bytes і created_at; database blob був жорстко прив'язаний до моделі.
- Існували database та local режими, але без єдиного MediaStorage контракту і без S3-compatible backend.
- Доступ уже класифікувався як public / participant_private / staff_private / superadmin_private; невідомі категорії були secure-by-default і не ставали public.
- Existing integrity logic уже знаходив missing references та orphan MediaAsset, але не мав checksum/corruption/duplicate MIME lifecycle-моделі.
- Normal delete для database media фізично видаляв MediaAsset; v1.19.1 замінює це на quarantine-first lifecycle.
- Quest proofs, consents, activity results, event images та інші mapped *_path поля залишаються backward-compatible через canonical `/media/<id>` або legacy local paths.
- Backup/restore, security, permissions, privacy suppression, XP, attendance та gamification не послаблюються.
