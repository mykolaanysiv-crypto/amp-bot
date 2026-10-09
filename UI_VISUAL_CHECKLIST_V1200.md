# AMP XP v1.20.0 — UI visual regression checklist

For every item verify desktop 1440px, laptop 1024px, tablet 768px, mobile 390px and 320px; keyboard-only flow; visible focus; no page-level horizontal overflow; light/dark mode; empty/error/restricted states where applicable.

- Login, Telegram OTP, Passkey login.
- Dashboard: KPI, operational alerts, tables, upcoming events.
- Events list/detail/create/edit and QR/scanner links.
- Participants list/detail, registrations, ambassadors.
- Quests, quick XP, volunteer tasks, activities.
- Surveys list/detail/response.
- Badges, rewards, giveaways, seasons, leaderboard/goals.
- Opportunities, ideas, requests, donations, broadcasts.
- Analytics/report pages and export controls.
- Notification Center.
- Security Center and account security/passkeys.
- System Health, Operations, Data Integrity, Media Integrity.
- Settings, permissions, audit detail.
- Public event/opportunity pages and Telegram event scanner.

Sidebar acceptance:
- expanded desktop;
- collapse to icon rail;
- preference persists after navigation/reload;
- tooltips/titles remain available in compact mode;
- mobile hamburger opens drawer;
- backdrop and ESC close it;
- Tab/Shift+Tab stay inside drawer;
- focus returns to hamburger;
- body does not scroll behind open drawer.
