# AMP v1.17.0 — Giveaways & Auditable Randomizer

## Що додано

- **Web → Гейміфікація → 🎲 Розіграші**.
- Аудиторії: усі активні, команда АМП, учасники конкретної події, обрані ролі, конкретні користувачі.
- Режими участі:
  - `automatic` — користувач бере участь автоматично, якщо входить у поточну аудиторію;
  - `task` — користувач виконує умову до дедлайну, подає текст і обов'язкове фото, адміністратор допускає/повертає/відхиляє.
- До 5 типів подарунків; кожен має назву, опис, фото, `quantity`.
- Кількість переможців = сумі `quantity` усіх подарунків.
- Один користувач може виграти максимум один подарунок у межах розіграшу.
- Рандомайзер: 256-bit random seed (`secrets.token_hex(32)`) + стабільний SHA-256 ordering; seed та algorithm зберігаються для аудиту.
- Повторний draw після зафіксованого результату не створює нових переможців.
- Після draw переможці відображаються під конкретними подарунками та отримують повідомлення через Notification Center / durable outbox.
- Telegram → «Мій профіль» → **🎲 Розіграші**: лише активні розіграші, доступні конкретному користувачу.
- Task-proof у Telegram: текст + обов'язкове фото; proof media — staff-private.
- Prize media — public, щоб фото подарунка могло безпечно відображатися у participant UX.

## Схема БД

Alembic head: `20260919_0007`.

Нові таблиці:
- `giveaways`;
- `giveaway_prizes`;
- `giveaway_entries`;
- `giveaway_winners`.

Після міграції SQLAlchemy metadata: **61 таблиця**.

## Інваріанти

- Тільки additive Alembic migration; production DB не видаляти/не пересоздавати.
- Notification Center/outbox — canonical шлях winner notifications.
- У task-розіграші до draw допускається тільки `GiveawayEntry.status == approved` і лише якщо користувач досі входить у цільову аудиторію.
- Автоматична аудиторія обчислюється на момент перегляду/draw, тому новий eligible user не потребує ручного додавання.
- Draw блокується, якщо допущених унікальних користувачів менше, ніж одиниць подарунків.
- Проведений draw незмінний; подарунки й основні параметри після `drawn` не редагуються.
- Час через canonical Clock; не використовувати naive `datetime.utcnow()`.

## Перевірка у build-середовищі

- `python -m compileall -q app scripts tests migrations` — PASS.
- `python -m scripts.production_preflight` — PASS для v1.17.0.
- `alembic heads` — `20260919_0007 (head)`.
- Jinja parse — 56/56 templates PASS.
- SQLAlchemy metadata — 61 tables.
- 62 focused/static regression checks — PASS.
- 2 нові async behavior tests для фактичного draw/audience додані, але локально не виконані через відсутність `aiosqlite` у контейнері; вони мають пройти у штатному `requirements-dev`/GitHub gate.
