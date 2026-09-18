# AMP XP / «АМПасадори» v1.15.0.1 — Donation Badge CI Hotfix

## Причина
GitHub regression suite зупинявся на `test_donation_badges_have_ukrainian_labels_and_protected_rules`: тест вимагав видимий український маркер `Системний донатний бейдж`, але після редизайну badges.html залишився лише загальний текст про захищене системне правило.

## Виправлено
- У Web-картці built-in донатних бейджів знову показується `💙 Системний донатний бейдж`.
- Захищені критерій/поріг залишаються незмінними, а видимі поля можна редагувати як у v1.15.0.
- `test_v1150_targeting_event_analytics.py` зроблено patch-compatible для лінійки 1.15.x.
- `tests/test_v1741_features.py` переведено з deprecated `datetime.utcnow()` на canonical `clock`.
- Додано production-preflight guard на український системний донатний label.

## База даних
Нових schema changes немає. Очікуваний Alembic head: `20260918_0004`.
