# АМП XP / «АМПасадори» v1.10.0.1 — 🧪 Full Regression Alignment Hotfix

## Навіщо цей patch

Після v1.10.0 повний `pytest -q` в актуальному локальному середовищі виявив 4 regression failures. Вони були не новими production-помилками, а старими тестами, які все ще перевіряли архітектурні правила попередніх релізів:

1. `tests/test_reliability.py` очікував state у legacy `notification_deliveries`, хоча з v1.9.0 активний outbox — `notifications`.
2. `tests/test_v181_features.py` очікував масовий `opportunity_created`, хоча з v1.9.2 opportunities персоналізовані через explicit interests/matching.
3. `tests/test_v1821_calendar_event_ops.py` вимагав literal `timedelta(hours=2)`, хоча з v1.10.0 waitlist reservation керується runtime setting і default дорівнює 120 хв.

## Що змінено

- Regression tests приведені до поточної архітектури.
- Канонічний notification retry перевіряється по `Notification.status`, `scheduled_at`, `retry_count`.
- Smart Opportunities regression перевіряє `refresh_matches_for_opportunity` і delivery source `opportunity_match`.
- Waitlist regression перевіряє runtime key `events.waitlist_reservation_minutes`, dynamic `timedelta(minutes=reservation_minutes)` та default 120 хв.
- Version/CSS cache assertions у всіх релізних тестах переведені на `1.10.0.1`.
- Production business logic не змінювалася.

## База даних

- Нових таблиць: 0.
- Нових колонок: 0.
- Схема: 47 таблиць, як у v1.10.0.
- Окрема міграція не потрібна.

## Встановлення

Див. `COMMANDS_V11001.txt`. Перед deploy як завжди рекомендований Heroku PostgreSQL backup.

## Важливо

Це насамперед QA hotfix. Його мета — щоб повний regression suite не давав false-negative через застарілі припущення старих версій.
