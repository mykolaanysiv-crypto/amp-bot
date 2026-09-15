# АМПасадори v1.12.0.1 — Startup Bootstrap Hotfix

## Причина
Під час Heroku release phase v1.12.0 `bootstrap_defaults()` звертався до `_bootstrap_lock`, який не був перенесений зі старого `services.py` під час refactor. Release завершувався `NameError`.

## Виправлення
У `app/domain_services/bootstrap.py` відновлено process-local `asyncio.Lock()`. Зміни схеми БД відсутні.

## Деплой
Накласти v1.12.0.1 поверх поточної Git-папки, commit, `git push heroku HEAD:main`. Після успішного release: `heroku ps:scale web=1 worker=1 -a amp-bot-ver-1-5-0`.
