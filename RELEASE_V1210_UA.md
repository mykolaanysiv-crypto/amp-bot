AMP XP v1.22.0 — retains historical v1.21.0 evidence and baseline.
# AMP XP v1.21.0 — Product Experience Redesign

## Статус
Release Candidate до проходження повного CI/CD, PostgreSQL 18 integration, backup restore verification та production visual QA.

## Схема
Alembic head: `20261010_0018`. Нова міграція не додається.

## Що змінилось
- Product-first dashboard «Огляд простору» з чіткою ієрархією KPI, найближчих подій, attention і гейміфікації.
- Role-aware sidebar: **Робочий простір / Адміністрування / Система / Підтримка**.
- Усі існуючі admin/superadmin tools збережені за permissions; відсутність блоку на mockup не означає видалення route або capability.
- Events workspace отримав новий header, ширший layout і створення події через centered accessible dialog.
- Registrations перебудовані як full-width approval workspace з компактними icon actions.
- Ideas перебудовані у discovery grid із сучасними status/filter patterns і переходом до Opportunities.
- Gamification presentation оновлено навколо streaks/rewards/seasons без зміни правил XP, серій, ліг чи нагород.
- Додано Product Experience design layer з semantic colors, легкими glass-акцентами, м’якими тінями, consistent spacing і глобальним захистом від поділу слів по літерах.

## Свідомі зміни regression expectations
Історичні source-gates, які перевіряли точний cache/version token v1.20.3.1, оновлені на v1.21.0. Source-gates, прив’язані до старої конкретної іконки (`event`/`clipboard`), оновлені лише там, де семантичний icon mapping свідомо змінився на `calendar`/`registration`. Самі production requirements — наявність навігації, функціональності та permission boundaries — не послаблені.

## Що НЕ змінено
- XP та wallet semantics;
- attendance / QR;
- quests domain behavior;
- badges / rewards semantics;
- permissions як server-side source of truth;
- CSRF / CSP;
- 2FA / WebAuthn;
- privacy suppression;
- audit trail;
- media lifecycle;
- backup/restore release gate;
- schema drift gate.

## Role-based UI
Візуальні макети покривають основні product pages, але не є повним списком модулів. Security Center, Media Integrity, Operational Issues, health, audit, permissions, reports, exports, broadcasts, settings та інші protected tools залишаються у системі й доступні лише відповідним ролям/permissions.

Participant-facing архітектура передбачена як простіший рівень UX. v1.21.0 не надає звичайному participant системних/службових інструментів і не розширює permissions через presentation layer.


AMP XP v1.22.1 UI refinement candidate; see RELEASE_V1221_UA.md for scope and verification.

AMP XP v1.22.2 CI hotfix candidate; see RELEASE_V1222_UA.md for status.
