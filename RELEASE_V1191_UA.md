# AMP XP v1.19.1 — Media Storage & Data Lifecycle

Версія 1.19.1 відокремлює media-бізнес-логіку від фізичного сховища та додає керований життєвий цикл файлів без автоматичного перенесення production media.

## Основне
- `MediaStorage` abstraction.
- `DatabaseMediaStorage`, `LocalMediaStorage`, `S3CompatibleMediaStorage`.
- S3-compatible SigV4 підтримка для AWS S3, Cloudflare R2 та Backblaze B2.
- checksum SHA-256, content-based MIME sniffing, 20 MiB size validation.
- Deep integrity scan: missing, orphan, duplicate checksum, corrupt checksum, invalid MIME, oversized media.
- Web Media Integrity Center: `/admin/media-integrity` (superadmin-only).
- Lifecycle: detect → candidate → review → quarantine → delete.
- Hard-delete заборонено автоматично; остаточне видалення можливе лише після quarantine, без active references і з ручним підтвердженням `ВИДАЛИТИ`.
- Safe database → S3 tool: `dry-run`, `copy`, `verify`, `switch`, `rollback`.
- `switch` не видаляє database bytes; rollback залишається можливим.

## Schema
Additive Alembic revision: `20261007_0016 -> 20261008_0017`.
Нові MediaAsset metadata: storage backend/key, checksum, detected MIME, lifecycle/integrity state, review/quarantine/verification timestamps. `data` стає nullable для external storage.

## Backward compatibility
Existing `/media/<id>`, `/uploads/...`, `/private/...`, quest proofs, consents, activity results and event images remain supported. XP, wallet, attendance, QR, quests, rewards, permissions and privacy suppression semantics are unchanged.

## Production safety
No production media is moved automatically during deploy. S3 migration is always explicit and phase-based. Backup verification and schema drift remain blocking release gates.
