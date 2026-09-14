# AMP XP / АМПасадори v1.8.0 — production update

## 1. Що це за реліз

v1.8.0 — реліз **🔔 Admin UX** поверх v1.7.4.1. Він не скасовує security v1.7.3, reliability/idempotency v1.7.4 або event/referral/document-функції v1.7.4.1. Основна мета — зробити щоденну роботу команди швидшою й послідовнішою.

## 2. Перед deploy

```bash
heroku pg:backups:capture -a YOUR_APP
heroku pg:backups -a YOUR_APP
```

Перевірте, що збережені чинні Config Vars (`BOT_TOKEN`, `DATABASE_URL`, `WEB_SESSION_SECRET`, `SUPERADMIN_IDS`, `PUBLIC_BASE_URL` та інші production values).

## 3. Deploy

Стандартний Procfile/release workflow залишається чинним:

```bash
git add .
git commit -m "AMP XP v1.8.0 Admin UX"
git push heroku main
```

Або deploy вашим поточним Heroku workflow. Release command виконає idempotent DB initialization.

## 4. Міграція БД

Нових таблиць у v1.8.0 немає. Metadata залишається на **44 таблицях**. Ручний SQLite → PostgreSQL перенос після deploy **не потрібний**.

## 5. Що перевірити після deploy

1. `/health` показує `1.8.0`.
2. `/admin/dashboard` містить блок `🔔 Потребує уваги`.
3. Верхній `🔎 Пошук` знаходить AMP-ID, ПІБ і доменні сутності; телефон/email — тільки для superadmin.
4. Sidebar розбитий на логічні групи; `/admin/calendar` і `/admin/settings` відкриваються.
5. На списках учасників, подій, квестів, задач, активностей, можливостей, опитувань, ідей і звернень працюють smart filters та `Скинути`.
6. У Telegram почніть `💡 Нова ідея`, а потім натисніть іншу кнопку головного меню: текст кнопки не записується у форму; з’являється `Так / Ні`; `Ні` продовжує форму, `Так` переходить у вибраний розділ.
7. `/admin/system-health` має однакові action-кнопки; при failed Telegram deliveries доступний `↻ Повторити невдалі Telegram-повідомлення`.
8. Перевірте scheduler job `participant_inactivity`: participant/ambassador, що 60 днів не взаємодіє з ботом, переводиться у `inactive`; blocked/staff не зачіпаються.

## 6. Політика 60 днів

- `last_activity_at` є основною датою; для профілю без неї використовується `created_at`.
- На 55-й день система ставить durable warning у Telegram.
- На 59-й день — фінальне warning.
- На 60-й день profile `participant/ambassador` переводиться у `inactive` і доступ закривається.
- Фізичного DELETE з БД немає: історія, XP, звітні зв’язки та аудит зберігаються.
- `blocked` профілі та staff-ролі не потрапляють під автоматичну деактивацію.
- Якщо referral ще входить у 30-денне правило v1.7.4.1, чинний idempotent clawback застосовується тим самим workflow.

## 7. Rollback

Код можна відкотити стандартним Heroku rollback. Оскільки v1.8.0 не додає нових таблиць, rollback не вимагає destructive schema rollback.
