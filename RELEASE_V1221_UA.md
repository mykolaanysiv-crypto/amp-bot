# AMP XP v1.22.1 — UI Refinement, source candidate

**Статус:** кодова збірка для локальної перевірки / CI. **НЕ production-ready**. Жодного деплою не виконано.

## Реальні внесені зміни
- Виправлено чорні суцільні SVG: macro icon тепер явно задає `fill=none`, `stroke=currentColor`, stroke 1.8, linecap/linejoin.
- Додано окремий каскад `ui_refinement_1221.css` для плавних hover/pressed, видимого фокусу, зменшення руху, dark-surface підтримки, форм, кнопок та адаптивності.
- Головний hero використовує нейтральну SVG-ілюстрацію з наданого пакета, без маскота.
- Топ-5 активних користувачів: XP з наявного SQL aggregate, назви ліг з `runtime_leagues()` та `league_for_xp()`. Не замінює сезонний рейтинг; базується на чинному загальному XP-відборі.
- Події: кнопки «Застосувати» й «Скинути» згруповано; правила для одного рядка на широких екранах.
- Прибрано дубльовані форми редагування зі сторінок деталей квесту і волонтерської задачі; редагування лишається в каталозі, routes не змінено.
- Уніфіковано токени кешування файлів v1.22.1, VERSION, VERSION_CHECK, app fallback, release preflight / consistency.
- Додано шість простих Python source-regression тестів.

## Результати перевірок у середовищі
- `python -m scripts.production_preflight` — PASS.
- `python -m scripts.release_consistency_check` — PASS; Alembic head 20261010_0018.
- `python -m compileall -q app scripts` — PASS.
- Розбір усіх Jinja2 шаблонів — PASS.
- 6 із 6 Node JS smoke-тестів — PASS.
- 15 із 15 вибраних UX/static pytest — PASS.
- Повний `pytest -q --ignore=tests/integration` — НЕ ПРОЙШОВ етап collection через відсутність `aiogram`; доступ до PyPI відсутній.

## НЕ завершено / НЕ підтверджено
- Повний браузерний UX-аудит реальних авторизованих екранів та screenshot-based QA; залежності застосунку не встановлені повністю.
- Наскрізні інтеграційні тести з PostgreSQL 18, Telegram, QR, XP та restore перевірка реальної backup.
- Доведення темної теми кожного компонента до WCAG AA на реальних даних.
- Повний лічильник **непрочитаних** сповіщень: модель Notification зараз є outbox (`queued/retry/sent/failed`), а не read/unread. Щоб не підміняти невдалу доставку статусом непрочитаного, badge не додано без окремої моделі/контракту.
- Динамічні редактори й наскрізний редизайн усіх адміністративних сторінок.
- Конфігураційна перевірка різниці вихідного архіву з поточною GitHub-гілкою (репозиторій міг отримати новіші коміти після ZIP).

## Безпечне перенесення в GitHub
Використовуйте окрему release-гілку на актуальній базі. Порівняйте з останніми змінами репозиторію, застосуйте patch або скопіюйте файли без `.git`, `.venv`, `.env`; не робіть force-push. Усі GitHub Actions і staging мають пройти до merge.

## Деплой і rollback
Не розгортати зараз. Перед деплоєм: повний CI, staging PostgreSQL 18, alembic upgrade на копії, Telegram mock, QR/XP idempotency, окреме відновлення backup з `pg_restore` сумісної версії, smoke endpoints. Зберігати попередній Git SHA/release; rollback через повернення попереднього Git release та узгоджений план БД (не використовувати downgrade навмання).
