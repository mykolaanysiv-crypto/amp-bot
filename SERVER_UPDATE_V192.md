# АМП XP / «АМПасадори» v1.9.2 — 🌍 Smart Opportunities & 🏆 Seasons History

## Що змінилося

### 🌍 Smart Opportunities
- У профілі учасника з’явилися явні інтереси: **Волонтерство, Освіта, Гранти, Обміни, Підприємництво, Культура, Спорт, IT, Медіа**.
- Персональний matching враховує **вік, вибрані інтереси, населений пункт, формат і дедлайн**.
- Категорії вразливості **не використовуються** для автоматичного profiling/matching.
- Якщо інтереси ще не обрані, автоматичні рекомендації не створюються, але загальний каталог можливостей залишається доступним.
- Telegram показує match %; Notification Center формує персональний digest максимум із 3 нових релевантних можливостей.
- Web-каталог отримав таргетинг за населеними пунктами та лічильники matched/interested.

### 🏆 Seasons & History
- Після завершення сезон фіналізується як історичний snapshot, а не просто вимикається.
- Зберігаються:
  - TOP-3 сезону;
  - переможці кожної з 6 ліг;
  - рекорд сезонного XP;
  - рекорд streak;
  - рекорд волонтерських годин;
  - видані бейджі та їхня статистика;
  - розподіл за лігами;
  - повний фінальний leaderboard.
- У Telegram-профілі та Participant 360 є `🕰 Історія сезонів`.
- У web є окрема detail-сторінка сезону.
- Створення нового сезону фіналізує чинний; startup не реактивує вже архівний/finalized сезон.

## База даних
v1.9.2 використовує **47 таблиць**. Release-ініціалізація additive/idempotent:
- `users.opportunity_interests_json`;
- `opportunities.target_settlements`;
- `seasons.finalized_at`;
- `seasons.history_json`;
- нова таблиця `opportunity_matches`.

Повторний перенос SQLite → PostgreSQL **не потрібний**.

## Встановлення
1. Зробіть Heroku PostgreSQL backup.
2. Скопіюйте v1.9.2 поверх робочої папки, не перезаписуючи `.git`, `.env`, `.venv`, `data`.
3. Встановіть/перевірте `requirements.txt`.
4. Перевірте `VERSION.txt` = `1.9.2`.
5. Запустіть compile/static checks та targeted regression.
6. Зробіть commit і `git push heroku main`.
7. Release-команда сама застосує additive/idempotent DB upgrade.
8. Перевірте `/health`, `🌍 Можливості`, історію сезонів та scheduler у `🩺 Стан системи`.

Детальні команди: `COMMANDS_V192.txt`.
