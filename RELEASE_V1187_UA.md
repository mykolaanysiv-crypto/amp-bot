# AMP XP / «АМПасадори» v1.18.7 — Reproducible Production Baseline

Дата підготовки: 07.10.2026

## Мета релізу
v1.18.7 — технічний baseline-реліз без нових participant/business features. Він фіксує актуальну post-v1.18.6 production-кодобазу після hotfix, робить прямі dependency versions детермінованими, перетворює dependency audit на blocking gate та автоматизує контроль версії/документації/release manifest.

## Джерело
Source artifact: `amp_bot_v1186_release_git.zip` (SHA256 `d8c86cff18b2daa285ed14946525f894929f9f0e8b82995b98b66d4b590e34cb`); source Git HEAD у наданому архіві: `7188d8a` (`hotfix/v1.18.6-heroku-url`). Старіша `amp_bot_v1186(1).zip` не використовувалась як source of truth.

## Ключові зміни
- VERSION/static cache/source gates → `1.18.7`.
- Alembic head без змін: `20260925_0015`; нової міграції немає.
- Exact direct production/dev lock files та автоматичний lock consistency gate.
- `pip-audit` blocking; `pip check` обов’язковий у CI.
- Release/documentation consistency gate для VERSION, README, HEROKU_DEPLOY, manifest, cache token, Alembic head і required runtime files.
- Docker install через production lock; local Docker Compose PostgreSQL 18 через public ECR.
- Safe deprecation cleanup у тестах: canonical Clock замість `datetime.utcnow()`, Alembic `path_separator=os`, openpyxl stdlib copy.
- Збережено v1.18.6 security/reliability guarantees без зміни XP/attendance/wallet/QR/gamification/privacy/permissions semantics.

## Dependency locking
`requirements.lock` і `requirements-dev.lock` містять exact direct pins. У цьому offline build environment повний clean install/resolution і vulnerability audit не можуть бути виконані через відсутність мережевого доступу; вони залишаються mandatory/deferred to GitHub Actions і реліз не вважається production до green gate.

## Database
- Alembic head: `20260925_0015`
- New migration: NO
- Runtime schema mutation: forbidden

## GitHub Actions major versions
Існуючі `actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4` навмисно не підвищувались у цьому baseline-релізі без окремого CI-only validation. Dependabot updates слід перевіряти окремими PR.

## Production status
Кандидат v1.18.7 НЕ вважати production, доки не пройдено PR/main Production Gate, restore-verified backup, Heroku deploy та post-deploy health/version smoke.

## Аудит
Передрелізний технічний аудит збережено в `AUDIT_V1187_BASELINE_UA.md`.
