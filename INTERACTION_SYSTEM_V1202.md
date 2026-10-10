# AMP XP v1.20.2 — Interaction System

## Tabs
Account tabs — semantic `role=tablist/tab/tabpanel`. Активний state зберігається у `?tab=profile|achievements|security|sessions`. Keyboard: ArrowLeft/ArrowRight/Home/End. Клік не виконує anchor-scroll.

## Dialogs
Profile/avatar flows використовують dialog architecture з backdrop, ESC, focus management та server-side forms. JS — progressive enhancement; backend CSRF/permissions залишаються джерелом істини.

## Account menu
Topbar account button керує compact menu з `aria-expanded`, close on outside click/ESC і focus return.

## Participant combobox
Superadmin-only endpoint `/admin/security/participant-search` повертає мінімальний набір полів для пошуку AMP participant. Combobox зберігає canonical `linked_user_id` у hidden field, але адміністратор працює з AMP-кодом/ПІБ/username.

## Toasts
Server flash messages progressive-enhanced у `role=status` toast copies. Desktop — top-right, mobile — bottom; animation slide/fade.

## Avatar preview
Вибраний локальний image file previewed через object URL; URL revoke after image load. Backend validation/media privacy залишаються чинними.

## Help Center
Category navigation перемикає visible card groups. Непорожній search query навмисно шукає cross-category.

## CSP
Interaction JS зберігається у static external file; `unsafe-eval`/inline JS не додаються.
