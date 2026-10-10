# AMP XP v1.20.1 — Manual UI / Visual Checklist

Version: **1.20.1**.

Перевірити щонайменше на 320, 375, 768, 1024, 1280, 1440 і 1920 px.

## App shell
- Sidebar expanded/collapsed не перекриває content.
- Стан sidebar зберігається.
- Mobile hamburger/drawer/backdrop/Esc/focus return працюють.
- Topbar search/user/theme не обрізаються.

## Внутрішні блоки
- H1 не обрізаються і не стають непропорційно великими.
- Page actions wrap без horizontal overflow.
- Cards мають однакову visual hierarchy та достатні gaps.
- Tables не ламають body width.
- Form controls не виходять за container.

## Media Integrity
- Header «Цілісність медіа» читається повністю.
- Quick/deep scan buttons wrap коректно.
- Summary metrics використовують auto-fit layout.
- Backend details/preformatted output scroll-иться тільки всередині свого блоку.

## Dialog/edit flow
- «Редагувати» відкриває modal там, де застосовано progressive enhancement.
- Form values не втрачаються при відкритті.
- Esc закриває dialog.
- Focus повертається на opener.
- Backdrop click поводиться передбачувано.
- Save/Cancel/destructive дії візуально відрізняються.
- Без JS legacy details edit-flow залишається доступним.

## Мій кабінет
- Avatar/fallback initials виглядають коректно.
- Edit profile modal працює.
- Avatar upload/remove працює.
- Bio/contact fields відображаються без overflow.
- Badge gallery і stats працюють із linked profile та без нього.
- 2FA/passkey/session controls не зламані.

## Help Center
- Search фільтрує cards.
- Quick filters працюють.
- FAQ доступний клавіатурою.
- Core instructions відповідають поточній системі.

## Security
- User without permission не отримує access лише через UI trick.
- CSRF hidden fields збережені.
- Security Center / permissions / account routes працюють.
- Sensitive values не відображаються випадково.

## Theme / accessibility
- Light/dark/system behavior узгоджений.
- Visible focus є на buttons/links/inputs.
- 200% zoom не робить content недоступним.
- Reduced motion вимикає decorative animation.
- Контраст readable у key controls/statuses.
