# AMP XP / «АМПасадори» v1.12.1.6 — Health JSON Serialization Hotfix

Причина hotfix: production `/health/dependencies` повертав HTTP 500 з `TypeError: Object of type datetime is not JSON serializable`. Runtime snapshot коректно зберігав `datetime` для worker/scheduler heartbeat, але `_health_response()` передавав payload напряму в `JSONResponse`.

Виправлення: HTTP boundary використовує `fastapi.encoders.jsonable_encoder()` перед `JSONResponse`. Це рекурсивно перетворює `datetime`/`date`/UUID та інші підтримувані типи на JSON-safe значення. Внутрішня модель health snapshot не змінена.

Додано regression test і production preflight guard. Схема БД та бізнес-логіка без змін.
