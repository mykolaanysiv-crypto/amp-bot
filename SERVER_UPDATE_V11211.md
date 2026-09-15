# AMP XP / «АМПасадори» v1.12.1.1 — Reward Catalog Refactor Hotfix

## Причина
Повний GitHub CI вперше пройшов ширший regression suite і заблокував реліз на тесті `test_default_space_rewards_seeded_as_repeatable_services`: після перенесення логіки з монолітного `services.py` функція `seed_default_space_rewards()` залишилась у `app/domain_services/gamification.py`, але константа `DEFAULT_SPACE_REWARDS` не була перенесена.

## Виправлення
- `DEFAULT_SPACE_REWARDS` перенесено у доменний модуль `app/domain_services/gamification.py`.
- Збережено всі 9 стандартних винагород та їх XP-вартість.
- Додано окремий швидкий regression test каталогу без БД.
- Схема БД не змінюється.
- Production Stability Gate, PostgreSQL 16 CI, health endpoints, worker/scheduler heartbeat та pool limits із v1.12.1 залишаються без змін.

## Важливо
Це приклад того, що CI gate працює як задумано: помилка не була допущена до автоматичного production deploy.
