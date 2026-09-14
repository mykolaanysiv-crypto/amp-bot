# АМП XP / «АМПасадори» v1.9.1 — Advanced Analytics & PDF Layout Fixes

## Що змінилося
- Cohort funnel: зареєструвалися → 1 відвідування → повернулися → регулярні → АМПасадори.
- Retention 30/90 днів.
- Внутрішній Engagement Score 0–100.
- Heatmap день тижня × година.
- Аналітичні KPI вирівняні по 4 картки в ряд; коректні переноси слів і статусів.
- PDF звіт автоматично додає сторінки, якщо KPI/події/категорії не влазять; інформація не обрізається.
- Excel має окремий аркуш Advanced Analytics.
- Схема БД не змінена: міграція БД для v1.9.1 не потрібна.

## Встановлення
1. Зробіть Heroku PostgreSQL backup.
2. Скопіюйте код v1.9.1 поверх робочої папки, не перезаписуючи `.git`, `.env`, `.venv`, `data`.
3. Встановіть `requirements.txt`.
4. Перевірте `VERSION.txt` = `1.9.1`.
5. Запустіть `python -m compileall -q app scripts tests` та targeted tests.
6. Commit і `git push heroku main`.
7. Перевірте `/health`, web-аналітику та формування PDF.
