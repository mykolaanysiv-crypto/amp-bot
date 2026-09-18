# AMP XP / «АМПасадори» v1.14.0.2 — Telegram Profile Import Hotfix

## Причина

Після додавання напряму відповідальності АМПасадора handler `app/handlers/participant_home.py` почав використовувати `UserRole.AMBASSADOR.value` у відповіді «👤 Мій профіль», але `UserRole` не був доданий до explicit import із `participant_common` після Architecture Completion. У runtime це дає `NameError` при відкритті профілю.

## Виправлення

- `UserRole` явно імпортовано у `participant_home.py`.
- Додано regression test `tests/test_v11402_profile_import.py`.
- Додано production-preflight guard: якщо `UserRole.AMBASSADOR.value` використовується у profile handler без explicit import, build блокується до deploy.
- Historical v1.14.0.1 version test зроблено forward-compatible для patch-релізів.
- Web static cache token синхронізовано з `1.14.0.2`.

## Сумісність

- Функціональність v1.14.0 / v1.14.0.1 збережена: donation XP, backfill, кабінети АМПасадорів, звітність, event QR.
- SQLAlchemy schema: 55 таблиць.
- Нова міграція саме для v1.14.0.2 не потрібна.
- Пакет все ще містить additive migration `20260917_0003`; якщо production ще на `20260915_0002`, вона буде застосована під час успішного release.
- Очікуваний Alembic head після deploy: `20260917_0003`.

## Smoke після deploy

1. Telegram → `👤 Мій профіль` має відкриватися без помилки.
2. Перевірити `⚡ XP`, `🏅 Бейджі`, `🎁 Винагороди`.
3. Для АМПасадора у профілі має показуватися напрям відповідальності та кнопка кабінету.
4. `web.1` і `worker.1` — `up`.
5. `/health/ready` та `/health/dependencies` — healthy.
6. `alembic current` → `20260917_0003 (head)`.
