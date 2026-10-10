# AMP XP v1.20.1 — UI/UX Audit

Версія аудиту: **1.20.1**.

## Вихідна точка

v1.20.0 уже створив сильний app shell, collapsible sidebar, mobile drawer, SVG icon system, modular CSS та accessibility baseline. Основний недолік: візуальні зміни були найпомітніші у shell/navigation, тоді як внутрішні content surfaces частково залишалися пласкими, надто широкими або залежними від legacy inline-edit patterns.

## Виявлені проблеми

1. **Внутрішні блоки** — багато legacy pages використовували однаковий white-card treatment без достатньої visual hierarchy.
2. **Page headers** — на широких екранах заголовки та action rows могли створювати надто велику композицію; довгі назви потребували контрольованого `clamp()` і wrapping.
3. **Media Integrity** — header/actions і summary cards потребували кращого balance та auto-fit layout.
4. **Inline editing** — історичні `<details>` редагування функціональні, але розтягують сторінку та погіршують orientation.
5. **Browser confirms** — системні `confirm()` візуально не належать продукту і мають слабший контекст.
6. **Help** — стара довідка не була повноцінним task-oriented Help Center.
7. **Web identity** — `/admin/account` був переважно security page, а не особистим кабінетом із bio/avatar/achievements.
8. **Emotional design** — потрібні контрольовані gradients, accent surfaces, stronger section hierarchy та subtle motion без «кислотності».
9. **Responsive limits** — внутрішні grids і headings потребували додаткових max-width/wrap guards для 320–1920 px.
10. **Icon consistency** — нові поверхні мають використовувати чинний AMP SVG system, а не вводити нові emoji як primary UI.

## Рішення v1.20.1

- `experience.css` як окремий design layer;
- `experience.js` як CSP-safe progressive interaction layer;
- branded `<dialog>` system;
- progressive conversion of legacy edit-details into dialogs;
- reusable confirmation dialog;
- searchable Help Center;
- web user cabinet;
- private profile avatars;
- explicit superadmin profile linking;
- stronger max-width/wrapping rules;
- dashboard/media/internal card polish;
- additive migration only for web-profile metadata.

## Вимоги, які аудит не дозволяє послаблювати

CSRF, CSP, backend permissions, 2FA/WebAuthn, audit trail, privacy categories, backup verification, schema drift, dependency audit, XP idempotency та media quarantine lifecycle залишаються production invariants.
