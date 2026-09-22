# AMP XP v1.18.0 — Operational Intelligence & Gamification Governance

## Operational Intelligence
- `/admin/operations` — черга конкретних операційних задач для суперадміна.
- Сигнали: реєстрація >24 год, failed notifications, подія завтра без reminder, feedback <30%, прострочені reservations, XP/wallet anomalies, reward anomalies, stale/missing verified backup.
- Кожна задача має severity, відповідального, посилання на джерело, статус open/resolved, примітку вирішення та аудит.
- Scanner лише виявляє проблему; небезпечні виправлення автоматично не виконує.
- Dashboard показує верхні відкриті задачі.

## Gamification Change Control
- Нова append-only таблиця `gamification_rule_versions`.
- Зберігаються rule key, entity, field, old/new values, author, reason, effective_at і created_at.
- Контроль охоплює runtime XP rules, події (base/prereg/no-show), квести, волонтерські задачі, активності, опитування, Quick XP, goals, team tasks та reward prices.
- `/admin/gamification/governance` — історія версій та керування league thresholds.
- Пороги ліг зберігаються в `SystemSetting` і читаються runtime-функцією `runtime_leagues()`.
- Зміна правил ніколи не перераховує історичні XP, wallet або XPTransaction автоматично.

## Database
- Previous head: `20260921_0013`
- Current head: `20260921_0014`
- New tables: `operational_issues`, `gamification_rule_versions`.
