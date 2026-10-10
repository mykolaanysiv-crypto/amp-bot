# AMP XP v1.20.3 — Design System Refinement & Module UX

## Статус
Release Candidate на основі production-бази v1.20.2. Реліз не змінює XP, attendance, QR, quests, rewards, permissions, privacy, 2FA/WebAuthn, media lifecycle, audit або backup semantics. Alembic head залишається `20261010_0018`; нової міграції БД немає.

## Навіщо реліз
v1.20.3 закриває системні UI/UX дефекти, які залишилися після великих редизайнів: вузькі контейнери, порожні зони праворуч, перенос слів по літерах, вкладені `span`-селектори, що ламали SVG-іконки, хаотичні групи кнопок, різні ширини modal-вікон та нерівномірні картки.

## Основні зміни
- Додано фінальний override layer `refinement.css`, який централізовано керує шириною, wrapping, spacing, grid, card/action layouts, modal sizing і responsive rules.
- Додано `refinement.js` із прогресивними reveal-анімаціями, прямою навігацією Help Center та адаптивним sizing редакторських modal-вікон.
- Виправлено першопричину порожніх іконкових блоків у звітах: стиль тепер застосовується лише до direct-child tiles, а не до вкладеного `<span class="icon">`.
- Аналогічно виправлено meta/chip компоненти подій, квестів, можливостей, опитувань, розіграшів та інших карток.
- Розширено desktop content width до `1720px`, при цьому текстові блоки зберігають читабельну довжину рядка.
- Уніфіковано кнопки, форми, таблиці, tabs, cards, action rows і modal-компоненти.
- Додано semantic SVG icons для реєстрацій, команди, подій, квестів, волонтерства, етапів, каталогу, винагород, історії та груп налаштувань.
- Реєстрації, команда АМП, ідеї, сезони, серії, звітність, розсилки, settings та інші робочі модулі краще використовують ширину viewport.
- Help Center quick-start більше не вставляє службові ключові слова в поле пошуку: картка напряму відкриває потрібну категорію.
- У detail сторінці можливості прибрано дубльовану кнопку `Копіювати`; залишено primary share та `Відкрити`.
- Для винагород без фото використовується стандартний брендований `reward-placeholder.svg`.
- Modal edit-flow має контрольовані standard/editor/wide widths, sticky footer, нормальні gaps і mobile viewport limits.
- Додано системний subtle reveal motion; `prefers-reduced-motion` повністю його вимикає.

## Backward compatibility
Існуючі routes, forms, CSRF, permissions, domain semantics та database schema не змінювалися. Новий JS є progressive enhancement; серверні форми залишаються джерелом істини.

## Відомі обмеження
Visual QA на всіх реальних production data states все одно потрібен після deploy. Особливо перевірити довгі user-generated тексти, таблиці з великою кількістю колонок та mobile widths 320–390px.

## Deployment
Використовувати `COMMANDS_V1203.txt`. Production merge дозволений лише після blocking CI, PostgreSQL 18 integration, schema drift, backup restore verification та health/version smoke.

## Rollback
Це UI-only release без нової Alembic migration. При необхідності rollback application release до підтвердженої v1.20.2; schema `20261010_0018` не downgrade.
