# AMP XP v1.19.0 — Security & Observability 2.0

## Статус
Release candidate. Не вважати production до підтвердженого merge/deploy та post-deploy smoke.

## База
Реліз створено тільки з наданої збірки AMP XP v1.18.7. Початковий Alembic head `20260925_0015`.

## Основні зміни

### Passkeys / WebAuthn
- Додано WebAuthn/passkeys для staff web-акаунтів.
- Обов'язкова user verification на authenticator.
- Passkey стає пріоритетним другим фактором після правильного пароля, якщо для акаунта є активний passkey і deployment має валідний WebAuthn origin.
- Telegram OTP не видалено: він залишається fallback/recovery.
- Enrollment passkey додатково вимагає поточний пароль.
- Credential id не може бути перенесений між staff-акаунтами.
- `WEBAUTHN_RP_ID` додатково перевіряється як hostname origin або його батьківський домен, щоб помилкова production-конфігурація не створювала непрацюючі credentials.
- Реєстрація, успішний/невдалий вхід, fallback і revoke записуються в audit.

### Security Center
Новий `/admin/security-center` під permission `security.manage` показує:
- failed login/MFA;
- тимчасові блокування;
- active/stale sessions;
- passkey/Telegram 2FA coverage;
- sensitive exports/media access;
- permission changes і security audit events;
- лише boolean/status encryption-key configuration, без secret values;
- verified backup та observability telemetry.

### Rate limiting
Додано server-side sliding-window protection для login, MFA/passkey, password reset, QR/check-in, sensitive exports, multipart uploads, passkey management і public share endpoints. Raw IP не зберігається як limiter key — використовується short SHA-256 hash у пам'яті процесу.

### CSP
- Додано enforced Content-Security-Policy з origin allow-list.
- Усі Jinja `<script>` отримують per-request nonce.
- Паралельно діє stricter nonce-first `Content-Security-Policy-Report-Only` без `script-src 'unsafe-inline'` для безпечного поступового видалення legacy inline event handlers.

### Observability 2.0
Додано:
- HTTP p50/p95/max і 5xx count;
- DB query p50/p95/max без SQL text/parameters;
- DB pool utilization;
- export p50/p95;
- Telegram API failure counter;
- notification queue size/failures/oldest age;
- scheduler max lag і recent/lifetime failures;
- backup age/verified restore time;
- media assets/storage size.

### Operational Intelligence
Persistent advisory signals розширено на:
- stale worker;
- stale scheduler;
- high login/MFA failure rate;
- DB pool pressure;
- high/critical data-integrity anomalies.

Існуючі failed notifications, backup, event reminder і low-feedback signals збережено. Нові alerts не виконують destructive action.

## Міграція
Нова additive migration:

`20260925_0015 -> 20261007_0016`

Створюється тільки таблиця `web_authn_credentials`. XP/attendance/gamification/participant schema не змінюється. Є downgrade.

## Backward compatibility
- Telegram participant flows не змінені.
- XP/wallet/attendance/gamification semantics не змінені.
- Existing staff password + Telegram OTP login збережено.
- Production без валідного HTTPS WebAuthn origin стартує; passkeys просто не активні.

## Безпекова модель
### До
Password + Telegram OTP, server-side sessions, CSRF, permissions, encrypted fields, audit, secure media, backup restore verification.

### Після
До всього попереднього додані phishing-resistant passkeys, step-up enrollment, security-specific rate limits, CSP/nonce rollout, central security posture view та security/operational telemetry.

## Відомі межі
- Limiter process-local і є defense-in-depth; account lockout у БД залишається authoritative для brute-force login. Якщо в майбутньому буде багато web dynos, потрібен distributed rate-limit backend.
- Enforced CSP поки залишає `script-src 'unsafe-inline'` через legacy Jinja event attributes. Stricter nonce-only policy працює Report-Only; повне видалення unsafe-inline — окремий наступний hardening step.
- Runtime latency metrics — bounded in-memory per process, не long-term APM. Sentry/logging залишаються зовнішнім observability шаром.
