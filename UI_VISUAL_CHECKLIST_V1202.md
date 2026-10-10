# AMP XP v1.20.2 — Manual Visual QA Checklist

Перевірити на 320 / 375 / 390 / 768 / 1024 / 1280 / 1440 / 1920 px.

## Global shell
- [ ] AMP logo не зміщується при avatar load / long account name.
- [ ] Expanded/collapsed sidebar стабільний, без обрізаних labels.
- [ ] Немає дубльованого великого account card/avatar.
- [ ] Topbar account dropdown відкривається, ESC/outside click закриває.
- [ ] Light/dark contrast читабельний.
- [ ] Немає horizontal page overflow.

## Мій кабінет
- [ ] Profile/Achievements/Security/Sessions реально перемикають panels.
- [ ] Клік вкладки не скролить вниз.
- [ ] Refresh з `?tab=security` зберігає вкладку.
- [ ] ArrowLeft/Right/Home/End працюють.
- [ ] Active indicator рухається плавно.
- [ ] Profile edit відкриває dialog, а не розтягує page.
- [ ] Avatar dialog має preview/upload/remove separation.
- [ ] Avatar не змінює geometry layout.

## Security accounts
- [ ] Participant linking має searchable combobox.
- [ ] Пошук за AMP-code/ПІБ працює.
- [ ] Numeric DB ID не потрібно знати вручну.
- [ ] Permission denial для non-superadmin зберігається.

## Help Center
- [ ] Category tabs перемикають content.
- [ ] Search знаходить результати між categories.
- [ ] Keyboard navigation працює.

## Detail pages
- [ ] Idea detail stepper/headers/icons узгоджені.
- [ ] Event detail/scanner labels читабельні без emoji UI icons.
- [ ] Cards використовують hover elevation/color feedback.

## Dialog / motion / feedback
- [ ] ESC та focus return.
- [ ] Modal open/close animation.
- [ ] Toast success/warning/error/info.
- [ ] Buttons/cards мають видимий hover/focus feedback.
- [ ] Reduced-motion мінімізує animation.

## Security regression
- [ ] Login/2FA/passkey.
- [ ] CSRF forms.
- [ ] Security Center / Media Integrity.
- [ ] Permissions/roles.
- [ ] No secret values exposed.
