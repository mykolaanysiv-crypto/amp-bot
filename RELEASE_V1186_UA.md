# АМПасадори / AMP XP v1.18.6 — Platform Hardening

**Дата підготовки:** 07.10.2026  
**Тип релізу:** технічний стабілізаційний реліз без нової Alembic-міграції.  
**База:** повна стабілізована збірка v1.18.5.  
**Alembic head:** `20260925_0015`.

## Мета релізу

v1.18.6 не додає великий користувацький модуль. Реліз посилює production-контур: однакове runtime-середовище, перевірку резервних копій перед деплоєм, post-deploy smoke, окремий ключ шифрування персональних полів, обмеження HTTP upload, контроль неприв'язаних медіафайлів та додаткові CI-перевірки.

## Що змінено

### 1. Єдиний Python runtime
- `.python-version`, GitHub Actions і Docker тепер орієнтовані на **Python 3.13**.
- Docker image змінено на `python:3.13-slim`.
- PostgreSQL service у CI переведено на **PostgreSQL 18**, як і restore-verified backup verifier.

### 2. CI/CD hardening
- Додано Node.js 22 та запуск `tests/js/test_admin_forms.js` у Production gate.
- Додано Ruff critical static checks (`E9,F63,F7,F82`).
- Додано `pip-audit` як advisory dependency vulnerability check; його результат поки не блокує реліз.
- Додано Dependabot для Python dependencies і GitHub Actions.
- Перед push у Heroku deploy job тепер:
  1. створює свіжий Heroku PGBackup;
  2. реально відновлює його в ізольований PostgreSQL 18;
  3. записує verified-backup marker у production DB;
  4. лише після успіху deploy-ить перевірений commit.
- Після deploy GitHub Actions опитує `/health/ready`, перевіряє `/health/live` і звіряє фактичну версію з `VERSION.txt`.

### 3. Окремий production key для шифрування полів
- У production (`DYNO`) `FIELD_ENCRYPTION_KEY` тепер обов'язковий, має бути не коротший за 32 символи і **не може збігатися** з `WEB_SESSION_SECRET`.
- Deploy workflow може безпечно створити dedicated key, якщо його ще немає.
- Старий session secret переноситься в previous-key ring як migration bridge, тому дані, зашифровані старим fallback-механізмом, залишаються читабельними.
- Після успішного deploy запускається `python -m scripts.rotate_field_encryption`, який переписує legacy sensitive ciphertext поточним dedicated key.

> Важливо: не видаляйте старі ключі з `FIELD_ENCRYPTION_PREVIOUS_KEYS`, поки не підтверджено успішну ротацію та читання історичних даних.

### 4. Політика свіжості verified backup
Нові runtime settings:
- `BACKUP_WARNING_AGE_HOURS=36`;
- `BACKUP_MAX_AGE_HOURS=48`;
- `BACKUP_UNKNOWN_GRACE_HOURS=24`.

Стани:
- до 36 год — `ok`;
- 36–48 год — `warning`;
- понад 48 год — `stale` і backup-health failure.

Operational Intelligence створює окремий medium issue для backup warning і critical issue для stale/invalid/unknown backup.

### 5. Server-side request-size protection
- Додано `WEB_MAX_REQUEST_MB`, default **25 МБ**.
- Unsafe `/admin` request перевіряється за `Content-Length` та фактичним накопиченим body до передачі form/multipart parser.
- Перевищення межі повертає HTTP **413 Payload Too Large**.
- Існуючий per-file limit 20 МБ залишається додатковим, більш суворим обмеженням для окремого файлу.

### 6. Data Integrity: orphan MediaAsset
- Data Integrity Center додатково шукає database media, на які більше не посилається жодне `*_path` поле моделей.
- Результат — advisory issue `orphan_media_assets` із прикладами ID/category/filename/size.
- **Автоматичне видалення не виконується**: очищення лишається ручною/окремо контрольованою операцією.

### 7. Dev/release tooling
У `requirements-dev.txt` додано:
- Ruff;
- pip-audit;
- pip-tools.

`pip-tools` у v1.18.6 є підготовкою до reproducible lock workflow. Runtime `requirements.txt` у цьому релізі **ще не замінено** lock-файлом, щоб не міняти production dependency graph без окремого повного dependency test cycle.

## Нові/змінені production env

```env
FIELD_ENCRYPTION_KEY=<окремий секрет >=32 символи>
FIELD_ENCRYPTION_PREVIOUS_KEYS=<попередні ключі через кому>
BACKUP_UNKNOWN_GRACE_HOURS=24
BACKUP_WARNING_AGE_HOURS=36
BACKUP_MAX_AGE_HOURS=48
WEB_MAX_REQUEST_MB=25
```

## Міграції БД

Нової Alembic-міграції **немає**. Head залишається:

```text
20260925_0015
```

Зміни стосуються runtime/config/CI/security/integrity logic, а не структури таблиць.

## Перед merge / production deploy

Мають пройти:

```bash
python -m compileall -q app scripts migrations tests
python -m scripts.production_preflight
node tests/js/test_admin_forms.js
pytest -q --ignore=tests/integration
pytest -q tests/integration
```

GitHub Actions додатково виконує Ruff, PostgreSQL 18 integration/Alembic gates, schema drift check, restore verification свіжого PGBackup і post-deploy health/version smoke.

## Rollback

Якщо code deploy потрібно відкотити, відкотити Git commit/Heroku release. Нової DB schema у v1.18.6 немає. **Не видаляйте dedicated/previous encryption keys під час rollback**, оскільки після ротації частина ciphertext може вже бути переписана новим ключем.
