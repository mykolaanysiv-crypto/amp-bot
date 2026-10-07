# AMP XP v1.19.0 — аудит базової production-збірки

Дата: 07.10.2026
База для розробки: наданий архів `amp_bot_v1187(1).zip`.
Початкова версія коду: **1.18.7**.
Початковий Alembic head: **20260925_0015**.
Цільовий head v1.19.0 після additive migration: **20261007_0016**.
Runtime baseline: **Python 3.13**, **PostgreSQL 18**.

## 1. Що перевірено перед змінами

### Auth і staff access
- Staff-акаунти зберігаються в `web_staff_accounts`.
- Паролі: PBKDF2-SHA256, strong-password policy, temporary-password flow.
- Після 5 невдалих спроб діє тимчасове блокування на 15 хв.
- Зміна пароля завершує інші активні web-сесії.

### Web sessions
- Server-side `web_admin_sessions` + signed browser session cookie.
- Сесії мають `created_at`, `last_seen_at`, expiry/revoke lifecycle.
- Role/permissions перечитуються з БД, тому зміна доступу застосовується до активної сесії.

### 2FA
- Для superadmin Telegram OTP є обов'язковим.
- Для admin Telegram OTP можна увімкнути.
- OTP має TTL і ліміт невдалих спроб.

### Permissions / CSRF / middleware
- Централізована permission map захищає critical admin routes від direct-URL bypass.
- Unsafe admin requests захищені CSRF.
- Cookie: SameSite=Strict; secure production mode; HSTS у secure mode.
- Є server-side whole-request size limit для admin request body.

### Encrypted fields
- `EncryptedText` використовує Fernet payload `enc:v1`.
- Production вимагає окремий `FIELD_ENCRYPTION_KEY`, відмінний від `WEB_SESSION_SECRET`.
- Є previous-key bridge і rotation workflow.

### Audit
- Логуються login/logout, невдалі входи, 2FA, password/security changes, sensitive exports/media, permissions, XP та critical actions.

### Health / Operational Intelligence
- Є `/health/live`, `/health/ready`, `/health/dependencies`, `/health`.
- Web/worker/schedulers мають heartbeats та stale detection.
- `OperationalIssue` уже підтримує persist/fingerprint/severity/status/assignee/action URL та auto-resolve тільки після повного повторного scan.
- До v1.19.0 уже контролювалися failed notifications, overdue reminders, low feedback, XP/reward anomalies, stale backup та інші operational signals.

### Notification Center / Sentry
- Notification outbox має retry/failure state, dedupe та scheduler delivery.
- Sentry optional; `send_default_pii=False`, request cookies/auth headers і user identifiers scrubbed.
- Structured logs redacts configured secrets.

### CI/CD / backup
- Python 3.13 + PostgreSQL 18.
- Exact direct dependency locks і blocking `pip-audit`.
- Alembic-only production schema.
- Fresh Heroku PGBackup restore-verifies against isolated PostgreSQL 18 before deploy.
- Post-deploy readiness/live/version smoke is mandatory.

## 2. Основні gaps, які закриває v1.19.0

1. Не було phishing-resistant WebAuthn/passkey другого фактора.
2. Security information була рознесена між account/security/audit/health pages.
3. Не було окремого server-side request rate-limiter для security-sensitive surfaces.
4. Browser security headers не мали CSP rollout із nonce.
5. Health показував стан компонентів, але не p50/p95 HTTP/DB latency та queue/pool/media telemetry одним зрізом.
6. Operational Intelligence не перетворював stale worker/scheduler, login-failure spike, DB pool pressure та high-risk integrity scan на persistent advisory issues.

## 3. Межі релізу

v1.19.0 не змінює XP, wallet, attendance, QR attendance semantics, quests, leagues, streaks, rewards, badges або participant Telegram workflows.

Єдина schema change — additive таблиця WebAuthn credentials. Існуючі staff/session/participant таблиці не переписуються.
