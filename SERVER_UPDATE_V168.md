# Оновлення АМП XP до v1.6.8

Версія v1.6.8 містить additive/idempotent зміни БД. Не запускайте повторну SQLite → PostgreSQL міграцію. Стандартний Heroku release/init додасть нові колонки та таблиці.

## Перед оновленням
1. Створіть Heroku PostgreSQL backup.
2. Збережіть локальний `.env` поза Git.
3. Переконайтесь, що робоча гілка чиста.

## Після deploy
Перевірте `/health` → `1.6.8`, логи, а потім smoke-test: фото активності, пакетна видача бейджа, нагадування/поля події, +10 XP за схвалену тестову ідею, цілі/місії, документи та згоди.

## Нові дані v1.6.8
- `activity_applications.result_image_path`
- `event_registrations.reminder_1h_sent_at`
- `badges.badge_type`
- `ideas.approval_xp_awarded_at`
- `goals.task_text`, `reward_xp`, `image_path`
- `users.media_consent_*`, `parental_consent_*`
- таблиці `goal_rewards`, `consent_history`
