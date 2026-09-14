# АМП XP / «АМПасадори» v1.8.2.3 — Telegram QR Scanner & Runtime Fixes

## Що виправлено

### 1. Internal Server Error — Календар
Причина була у шаблоні Jinja: `day.items` для Python `dict` інтерпретувався як метод `dict.items`, а не як список елементів календаря. У month/week view це давало runtime error.

Виправлення: ключ перейменовано на `entries`, template використовує `day.entries`.

### 2. Internal Server Error — Ідеї та Звернення
Feature routes використовували `IDEA_STATUSES`, `REQUEST_STATUSES`, `REQUEST_CATEGORIES`, `REQUEST_PRIORITIES`, але після модульного розділення ці константи фактично не були визначені. Route успішно імпортувався, але падав під час відкриття сторінки.

Виправлення: canonical workflow constants додані в `app/ui_labels.py`, а `ideas.py` / `requests.py` імпортують їх явно.

### 3. QR Scanner у Telegram
У Telegram admin-панелі з'явився `📷 QR Scanner`. Coordinator/admin/superadmin:
1. обирає активну подію;
2. scanner mode зберігає event ID у FSM;
3. сканує персональний QR-бейдж учасника звичайною камерою телефона;
4. QR відкриває Telegram deep-link `profile_...`;
5. якщо scanner mode активний, бот трактує deep-link як attendance scan;
6. registered/reserved/checked_in → attendance підтверджується idempotently;
7. незареєстрований → кнопка `Зареєструвати та підтвердити`.

Також scanner приймає AMP-ID вручну.

> Telegram Bot API не має окремої команди, яка примусово відкриває системну QR-камеру всередині чату. Тому scanner реалізовано через Telegram FSM + deep-link із персонального QR. Це не залежить від browser `BarcodeDetector`.

### 4. Підтримка браузерів
На сторінці події основним є `📲 QR Scanner у Telegram`. Endpoint сам отримує username бота і відкриває Telegram scanner deep-link. Це працює через звичайний link/deep-link у Chrome, Safari, Firefox, Edge та мобільних браузерах.

Browser-camera scanner залишено як додатковий режим для браузерів із `BarcodeDetector` + `getUserMedia`; якщо API немає, користувач переходить у Telegram або вводить AMP-ID вручну.

## База даних
Нових таблиць і полів немає. Standard release init можна запускати як завжди; окрема міграція не потрібна.

## Після deploy перевірити
- `/health` показує `1.8.2.3`;
- `📆 Календар` відкривається у День / Тиждень / Місяць;
- `💡 Ідеї` відкриваються без 500;
- `🆘 Звернення` відкриваються без 500;
- Telegram: `Адмін-панель → 📷 QR Scanner → подія`;
- scan персонального QR registered participant → attendance confirmed;
- scan незареєстрованого → `Зареєструвати та підтвердити`;
- web event detail → `📲 QR Scanner у Telegram`;
- логи Heroku не містять traceback по calendar/ideas/requests/scanner.
