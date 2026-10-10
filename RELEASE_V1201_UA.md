# AMP XP v1.20.1 — Visual Experience & User Profiles

**Статус:** Release Candidate до завершення GitHub/Heroku production gates.
**Версія:** `1.20.1`
**Alembic head:** `20261010_0018`
**Production baseline:** AMP XP v1.20.0.

## Мета релізу

v1.20.1 поглиблює дизайн-систему v1.20.0: зміни стосуються не лише sidebar та іконок, а й внутрішніх блоків, page headers, карток, форм, діалогів, Help Center та особистого кабінету вебкористувача. При цьому release не переписує платформу на SPA та не змінює доменні правила XP, attendance, QR, quests, badges, rewards, permissions, media lifecycle, security, backup або audit.

## Visual Experience

- Додано окремий `experience.css` поверх системних design tokens та compatibility layer.
- Посилено branded visual language: м’які AMP-градієнти, виразні surfaces, контрольовані elevation/shadow, accent colors і hover/focus transitions.
- Виправлено надмірну ширину/масштаб внутрішніх блоків: `page-shell` має контрольований максимум, заголовки мають `clamp()` і безпечне перенесення, action rows коректно wrap-яться.
- Media Integrity Center отримав адаптивний header, wrap дій, auto-fit summary grid і безпечні max widths.
- Dashboard отримав більш виразний experience hero та секційні SVG-акценти.
- Основні destructive confirmations переведено з browser `confirm()` на єдиний брендований `<dialog>`.
- Існуючі `<details>` edit-flow з `edit-action-button` прогресивно перетворюються на modal dialogs у JS. Без JavaScript вихідний server-rendered edit-flow залишається доступним.

## Діалоги та UX

Новий modal pattern підтримує:
- native `<dialog>`;
- backdrop;
- повернення focus до кнопки-відкривача;
- закриття через системну поведінку Esc;
- доступні заголовки/кнопки;
- responsive max width/height;
- `prefers-reduced-motion`;
- loading lock для submit-кнопок;
- без `unsafe-eval` і без послаблення CSP.

## Help Center

`/admin/help` перетворено на внутрішній searchable Help Center. Він містить інструкції щодо:
- старту роботи;
- подій, QR та attendance;
- participant profile 360°;
- власного кабінету;
- quests/XP;
- badges/rewards;
- surveys/feedback;
- analytics/reports/export;
- media lifecycle та S3 migration;
- permissions;
- Security Center;
- 2FA/passkeys/sessions;
- Telegram bot commands;
- system health/Operational Intelligence;
- troubleshooting;
- FAQ та «ЩО НОВОГО».

Пошук є progressive enhancement: весь контент залишається server-rendered і доступний без JavaScript.

## Мій кабінет

`/admin/account` тепер є повноцінним кабінетом користувача web-платформи:
- avatar;
- display name;
- роль/професійний підпис;
- «Про себе»;
- email/телефон;
- light/dark preference;
- 2FA/passkey status і керування;
- активні сесії;
- optional statistics та badge gallery з пов’язаного AMP participant profile.

Суперадміністратор може явно пов’язати web account з існуючим AMP participant ID у security accounts. Система **не вгадує** таку відповідність автоматично.

## Приватність профілю

Аватари web-профілів зберігаються в media category `staff_profiles`, яка входить до `STAFF_PRIVATE_MEDIA_CATEGORIES`. Поля `profile_bio`, `profile_email` і `profile_phone` використовують чинний `EncryptedText` / FIELD_ENCRYPTION_KEY, а не plaintext storage. Старий avatar при заміні/видаленні використовує чинний quarantine-first media lifecycle, а не silent hard-delete.

## База даних

Додано additive Alembic migration:

```text
20261008_0017 → 20261010_0018
```

До `web_staff_accounts` додаються nullable поля:
- `profile_title`;
- `profile_bio`;
- `profile_email`;
- `profile_phone`;
- `avatar_path`;
- `linked_user_id` → `users.id`.

Міграція має downgrade. Вона не змінює participant, XP, attendance, quest, reward або media tables.

## Backward compatibility

- Existing URLs збережені.
- Server-rendered Jinja architecture збережена.
- Старий edit-flow залишається fallback, якщо progressive modal enhancement недоступний.
- Existing permissions є backend source of truth; приховування UI не замінює permission checks.
- Existing CSRF/CSP/2FA/WebAuthn/security middleware не послаблені.
- Existing media storage/lifecycle v1.19.1 не змінений.

## Свідомо не зроблено

- Немає React/Vue rewrite.
- Немає автоматичної міграції production media.
- Немає автоматичного створення participant ↔ web account links.
- Немає hard-delete avatar bytes під час звичайного profile flow.
- Немає зміни XP/attendance/QR/gamification semantics.

## Deployment

Merge дозволено лише після blocking CI: dependency locks, release consistency, compileall, preflight, Ruff, JavaScript smoke, pip-audit, pip check, full pytest, PostgreSQL 18 integration, Alembic 0017→0018 + downgrade/upgrade, schema drift та backup restore verification. Після deploy перевірити `/health/live`, `/health/ready`, version `1.20.1`, Alembic `20261010_0018`, verified backup marker і `UI_VISUAL_CHECKLIST_V1201.md`.

## Rollback

Переважний rollback — code release rollback із залишенням additive schema `0018`: старіші v1.20.0 code paths ігнорують nullable profile columns. Alembic downgrade до `20261008_0017` допускається лише після backup і лише якщо профільні дані, які потрібно зберегти, відсутні або окремо експортовані.
