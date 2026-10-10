# AMP XP v1.20.3.1 — UI/UX Fix + Design Polish

## Призначення релізу
v1.20.3.1 — patch-реліз поверх підтвердженої кодової бази v1.20.3. Його мета — виправити першопричини UI/UX-дефектів без зміни доменної логіки AMP XP.

Основні проблеми, які закриває реліз: перенос слів по літерах, надмірні тіні, дубльована кнопка згортання sidebar у topbar, неправильне фарбування цілої картки через глобальні severity-класи, хаотичні action-групи, завеликі/зміщені modal-вікна, дублювання великих alert і toast-повідомлень, а також недостатньо семантична іконографіка на «Огляді».

## Що змінено
- Додано фінальний UI-шар `polish.css`, який централізовано забороняє hyphenation/word splitting, стабілізує button geometry, зменшує тіні, вирівнює action rows, cards, operations і modal-компоненти.
- Додано `polish.js` з централізованим компактним toast API (`window.AMPToast`) та захистом від порожніх editor-dialogs.
- Toast-повідомлення переміщено в нижній лівий кут контентної області; вони мають semantic icon, close button та не блокують UI.
- Виправлено root cause червоних/помаранчевих OperationalIssue-карток: severity background тепер застосовується тільки до `.severity-dot`, а не до всієї картки.
- Прибрано дубльовану desktop-кнопку згортання sidebar у topbar; керування sidebar залишається у самому sidebar.
- Topbar bell відкриває Notification Center, якщо користувач має відповідний permission.
- Додано semantic SVG icons: `dashboard`, `tasks`, `xp`, `opportunity`, `streak`, `season`, `gamification`, `notification`.
- «Огляд» отримав semantic icons усередині KPI-карток; Quick XP, Opportunities, Seasons, Gamification, Notifications і Dashboard більше не ділять випадкові/однакові піктограми.
- Транзитні server notices позначаються `data-toast-source`; постійні security/operational warnings залишаються inline.
- Modal-вікна примусово центруються, мають контрольовані standard/editor/wide widths і компактніші shadows/backdrop.

## Що не змінено
Не змінювались XP, attendance, QR, quests, badges, rewards, permissions, CSRF, CSP, 2FA, WebAuthn, privacy, media lifecycle, audit, backup, schema drift та інші backend/domain semantics.

## База даних
Нової Alembic migration немає. Alembic head залишається `20261010_0018`.

## Backward compatibility
Маршрути, backend форми, permission checks і server-rendered архітектура залишаються сумісними з v1.20.3.

## Deployment
Production deploy дозволений тільки після локальних/CI gates, PostgreSQL 18 integration, schema drift, fresh backup + restore verification та post-deploy health/version smoke.
