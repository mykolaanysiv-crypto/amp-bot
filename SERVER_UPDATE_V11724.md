# AMP XP v1.17.2.4 — Quest Proofs, Event End Time & Live Sync

## 1. Квести: optional photo proof

Participant flow тепер: `✅ Виконано` → «Є фото?».

- **Ні**: `QuestParticipation.status = completed`, фото очищується, заявка переходить у чергу перевірки координатором.
- **Так**: бот переходить у `QuestProofState.photo`, приймає одне фото, зберігає його у staff-private `quest_proofs`, після чого переводить submission у `completed`.
- Повторна/неактуальна подача не змінює вже оброблений submission.
- Після подачі користувач отримує підтвердження, що запит передано на обробку.

Суперадмін у деталях квесту може виконати **«🛡 Виконано вручну»** для joined/returned/completed participation. Причина мінімум 5 символів обов'язкова. Нарахування XP проходить існуючий idempotent `approve_quest_participation`, тому повторне підтвердження не має створювати подвійний XP.

## 2. Події: початок і завершення

`Event` отримав `ends_at`. Web create/edit та Telegram admin create flow збирають окремий час завершення. `ends_at <= starts_at` у web-формі блокується; Telegram flow при меншому/рівному end-time трактує завершення як наступний день.

Для історичних подій migration задає `ends_at = starts_at + 2 години`.

## 3. Вікно відмітки

Runtime settings:

- `events.checkin_open_before_minutes` — default **60 хв до початку**;
- `events.checkin_close_after_end_minutes` — default **60 хв після завершення**.

Обидва параметри редагуються у Web → Налаштування. Перевірка виконується на aware UTC timeline через `event_checkin_window()`.

## 4. Feedback після завершення

`events.feedback_after_end_minutes` — default **10 хв**. Scheduler орієнтується на `event_end_utc(event)`, а не на start/check-in timestamp. Запрошення на feedback створюються для фактичних учасників зі статусами `checked_in` / `attended`. Scheduler перевіряє умову раз на 60 секунд.

## 5. Live updates

Web layout має lightweight live regions. Якщо сторінка містить `[data-live-region][id]`, браузер раз на 5 секунд фоново завантажує поточний URL і замінює тільки змінені regions. Повний reload не виконується. Region не замінюється, якщо у ньому активний input або dirty form.

Для Telegram web-edit опублікованої події/квесту автоматично ставить відповідне system notification у delivery queue. Користувачу не потрібно виконувати `/start`; будь-яке повторне відкриття entity/callback також читає актуальні дані з БД.

## 6. Schema

Alembic:

- previous head: `20260921_0012`;
- current head: `20260921_0013`;
- `events.ends_at` + index;
- `quest_participations.proof_photo_path`.
