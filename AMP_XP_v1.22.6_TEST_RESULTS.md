# Результати перевірок AMP XP v1.22.6 RC

Перевірено в автономному контейнерному середовищі 14.10.2026 (без production-даних).

| Перевірка | Результат | Уточнення |
|---|---|---|
| `python -m compileall -q app scripts` | PASS | Синтаксис Python |
| `python -m scripts.production_preflight` | PASS | Статична перевірка релізу |
| `python -m scripts.release_consistency_check` | PASS | Версія 1.22.6, Alembic head 0019 |
| `python -m scripts.build_admin_css --check` | PASS | CSS відтворюється з вихідних модулів |
| Цільовий pytest | 61 PASS | Фронтенд, UI, UX, сповіщення, contract tests |
| JS перевірки (`tests/js/*.js`) | 6 PASS | Node smoke/contracts |
| Jinja2 парсер | 66/66 PASS | Синтаксис шаблонів |
| Chromium isolated browser fixture | 11 ширин PASS | 320, 360, 375, 390, 414, 430, 768, 1024, 1280, 1440, 1920 px; темна тема, sidebar, SVG, аудит, без переповнення |
| Повний pytest | BLOCKED | 3 помилки збору: відсутній пакет `aiogram`; НЕ зараховано PASS |
| Інтеграційні тести PostgreSQL 18 | NOT RUN | Немає ізольованого сервера/безпечного середовища |
| Браузерний E2E усіх захищених сторінок | NOT RUN | Немає запущеного застосунку та тестових облікових даних |
| GitHub Actions | NOT RUN | Не було доступу до GitHub |
| Heroku/production та backup restore | NOT RUN | Не виконувався деплой, не торкалися production БД |

**Пояснення про Chromium:** ізольований перегляд рендерив справжні Jinja2-шаблони і справжній `admin.css` із демонстраційними даними, без логіну/API. Це корисний візуальний smoke-тест, але НЕ доводить коректності авторизації, SQL-запитів або всіх сторінок.
