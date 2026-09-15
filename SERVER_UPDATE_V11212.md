# AMP XP / «АМПасадори» v1.12.1.2 — CI Compatibility Hotfix

Production Gate правильно виявив два класи regression у старих тестах: historical tests були жорстко прив'язані до `1.12.0`, а тест canonical Notification Center не знав про новий аварійний out-of-band канал `runtime_health.py`.

У v1.12.1.2 старі тести більше не блокують новий реліз тільки через зміну номера версії; вони перевіряють синхронність поточного VERSION/cache-buster. Runtime-health direct Telegram path дозволений лише як emergency channel для `SUPERADMIN_IDS`, щоб web monitor міг повідомити про мертвий worker/Notification Center.

Схема БД не змінюється. Накласти пакет поверх поточної Git-папки, commit і `git push origin main`. Не робити manual Heroku push: GitHub Production Gate має пройти першим.
