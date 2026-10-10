# UI/UX Interaction Audit — AMP XP v1.20.2

## Вихідна база
Аудит виконано на production-базі v1.20.1 перед внесенням interaction changes у v1.20.2.

## Виявлені проблеми
1. Account navigation візуально виглядала як tabs, але поводилася як anchor-scroll по довгій сторінці.
2. Account identity дублювалася між hero/topbar/sidebar/navigation, що створювало візуальний шум і ризик layout shift після avatar upload.
3. Profile linking вимагав numeric participant id замість людського пошуку.
4. Частина edit-flow все ще була побудована навколо expansion/inline presentation замість dialog interaction.
5. Системна iconography була змішана: SVG + історичні emoji у web templates.
6. Hover/motion feedback був нерівномірний: новий дизайн виглядав сучасно, але взаємодія залишалася статичною.
7. Help Center category controls потребували поведінки справжніх interactive panels.
8. На широких екранах окремі сторінки недовикористовували viewport; водночас довгі тексти не повинні безконтрольно розтягуватися.
9. Gradient hero/muted/placeholder states потребували додаткового contrast hardening.
10. Sidebar footer/logo/account regions мали бути стабільними незалежно від avatar/name length.

## Рішення v1.20.2
- semantic ARIA tabs + query persistence;
- unified interaction layer (`interaction.js`, `interaction.css`);
- compact account menu/footer without duplicate nav entry;
- real avatar rendering in global identity surfaces;
- accessible participant search combobox;
- dialog-based profile/avatar flows and avatar preview;
- unified SVG system for system-authored web UI;
- motion tokens/toasts/hover transitions;
- adaptive width/grid rules;
- category-based Help Center navigation;
- source gates against anchor-as-tabs regression and duplicate account navigation.

## Не змінено
Backend/domain behavior, security semantics, permission boundaries, XP/attendance/QR/gamification/media/backup logic не є предметом цього UI interaction refactor.
