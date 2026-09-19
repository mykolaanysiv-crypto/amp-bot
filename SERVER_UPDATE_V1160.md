# AMP v1.16.0 — Team Tasks & Restricted Team Events

## Що змінено

- Вкладка **АМПасадори** тепер працює як центр команди АМП і показує активних `ambassador`, `coordinator`, `admin`, `superadmin`.
- Додано **персональні завдання для команди** з виконавцем, описом, дедлайном та XP.
- Виконання завдання без звіту неможливо: у Telegram обов'язковий текстовий звіт, фото — необов'язкове.
- Адміністратор може підтвердити звіт, повернути на доопрацювання або скасувати завдання. XP нараховується один раз після підтвердження; task row блокується `FOR UPDATE` перед award.
- Telegram **Кабінет команди АМП** доступний для АМПасадорів, координаторів, адміністраторів та суперадміністраторів.
- Події отримали `access_scope`: `general` або `team`. Закриті team-події використовують той самий lifecycle, waitlist, QR/check-in, attendance, XP, feedback та аналітику, що й звичайні, але доступ контролюється server-side.
- У Telegram команда бачить дві категорії подій: **Загальні події** та **Події для АМПасадорів**. Звичайні учасники бачать лише загальні.
- Team-події не мають публічної share-сторінки й не потрапляють у broadcast для звичайних учасників.
- Виправлено зламану кнопку поширення можливості, де JavaScript міг відобразитися як текст через inline `tojson`.
- Уніфіковано стиль кнопок **✏️ Редагувати** через `.edit-action-button`.
- Оновлено застарілий порядок release в `HEROKU_DEPLOY.md`.

## Схема БД

Alembic head: `20260919_0006`.

Міграція додає:
- `events.access_scope` (`general` за замовчуванням);
- таблицю `team_tasks`.

Після міграції metadata містить **57 таблиць**.

## Критичні інваріанти

- Не змінювати production DB вручну; тільки `alembic upgrade head`.
- Release-order: `db.init()` → Alembic → `bootstrap_defaults()` → FastAPI lifespan.
- Team event access перевіряється на сервері, а не лише прихованою кнопкою.
- XP за team task видається лише після поданого звіту і лише один раз.
- Notification Center/outbox залишається canonical delivery path.

## Перевірка

- `python -m compileall -q app scripts tests migrations` — PASS.
- `python -m scripts.production_preflight` — PASS для v1.16.0.
- `alembic heads` — `20260919_0006 (head)`.
- Jinja parse: 54/54 templates PASS.
- Focused regressions v1.14–v1.16: 24/24 PASS.
- Повний runtime pytest у цьому контейнері не використано як production proof через відсутність runtime dependency `aiogram` / `aiosqlite`; авторитетний повний gate залишається GitHub Actions + PostgreSQL 16 integration + release smoke.
