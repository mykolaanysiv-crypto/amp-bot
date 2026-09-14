# АМП XP / «АМПасадори» v1.8.2.2 — Startup Hotfix

## Що сталося
Після deploy v1.8.2.1 dyno падав ще під час імпорту FastAPI routes. У логах:

`NameError: Fields must not use names with leading underscores; e.g., use 'csrf' instead of '_csrf'.`

Проблемний route: `POST /admin/events/{event_id}/scanner`.

## Причина
У сигнатурі route було `_csrf: str = Form("")`. FastAPI на поточному Pydantic v2 будує body model під час startup, а Pydantic v2 забороняє field names із leading underscore. Через це застосунок не міг стартувати взагалі.

## Виправлення
`_csrf` прибрано із Python-сигнатури route. Поле `_csrf` продовжує надсилатися з browser JavaScript, а `CSRFMiddleware` перевіряє його до виконання route. Тобто CSRF-захист залишається повністю увімкненим.

## Що НЕ змінено
- єдиний календар День / Тиждень / Місяць;
- web QR Scanner;
- waitlist і 2-годинний резерв;
- attendance statuses/workflow;
- security v1.7.3;
- reliability v1.7.4;
- Participant 360 та lifecycle;
- БД і дані.

## Deploy
1. Зробіть backup PostgreSQL.
2. Замініть код на v1.8.2.2.
3. Commit + `git push heroku main`.
4. Перевірте `heroku ps`, `/health`, логи та сторінку події з QR Scanner.

Міграція БД не потрібна понад стандартний idempotent release step.
