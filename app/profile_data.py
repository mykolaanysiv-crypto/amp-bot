from __future__ import annotations

import json


PRIVACY_NOTICE_VERSION = "2026-09-10-v1"
MEDIA_CONSENT_VERSION = "2026-09-12-v1"


def privacy_notice_text() -> str:
    return (
        "🔐 <b>Як АМП використовує ваші дані</b>\n\n"
        "Під час реєстрації ми просимо ПІБ, дату народження, населений пункт, "
        "контакти, стать, соціальний статус/категорії та відповідь щодо фото- і відеозйомки.\n\n"
        "<b>Для чого:</b> організація участі в подіях і активностях, зв’язок з вами, "
        "вікові правила, ведення волонтерських годин і XP, внутрішня та агрегована звітність, "
        "а також планування підтримки молоді.\n\n"
        "Чутливі категорії використовуються лише у внутрішній роботі уповноваженої команди. "
        "Вони не показуються у публічному QR-бейджі чи рейтингу. Доступ до повних персональних "
        "даних у вебпанелі обмежено суперадміністратором.\n\n"
        "1 — <b>Ознайомився/лась і продовжити реєстрацію</b>\n"
        "2 — Не продовжувати реєстрацію"
    )


def split_display_name(full_name: str | None, first_name: str | None = None, last_name: str | None = None) -> tuple[str, str]:
    """Return (first_name, last_name) for current and legacy participant rows.

    Registration stores ``full_name`` as ``Прізвище Імʼя``.  Older rows may not
    have the dedicated first_name/last_name columns populated, so participant
    greetings must fall back to the *second* token, not the surname.
    """
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    parts = [part for part in (full_name or "").split() if part]
    if not first:
        if len(parts) >= 2:
            first = parts[1]
        elif parts:
            first = parts[0]
    if not last:
        if len(parts) >= 2:
            last = parts[0]
        elif parts and parts[0] != first:
            last = parts[0]
    return first, last


def participant_first_name(user, default: str = "друже") -> str:
    first, _ = split_display_name(
        getattr(user, "full_name", None),
        getattr(user, "first_name", None),
        getattr(user, "last_name", None),
    )
    return first or default


# Social-status and vulnerability codes stay stable in the DB; labels can evolve.
VULNERABILITY_OPTIONS: list[tuple[int, str, str]] = [
    (1, "idp", "ВПО"),
    (2, "disability", "Людина з інвалідністю"),
    (3, "veteran", "Ветеран/ветеранка"),
    (4, "veteran_family", "Член родини ветерана/ветеранки"),
    (5, "fallen_defender_family", "Член сім’ї загиблого/загиблої Захисника/Захисниці України"),
    (6, "missing_person_family", "Член сім’ї зниклого/зниклої безвісти"),
    (7, "large_family", "Член багатодітної родини"),
    (8, "guardianship", "Особа під опікою/піклуванням"),
    (9, "difficult_life_circumstances", "Особа/сім’я у складних життєвих обставинах (СЖО)"),
    (10, "lgbt_plus", "ЛГБТ+"),
    (11, "other", "Інша категорія"),
    (12, "local_resident", "Місцевий житель/жителька"),
    (13, "no_category", "Не відношусь до жодної з перелічених категорій"),
]



GENDER_OPTIONS: list[tuple[str, str]] = [
    ("female", "Жіноча"),
    ("male", "Чоловіча"),
    ("other", "Інша / самовизначення"),
    ("prefer_not_say", "Не бажаю зазначати"),
]
GENDER_LABELS = dict(GENDER_OPTIONS)


def gender_label(value: str | None) -> str:
    if not value:
        return "Не зазначено"
    return GENDER_LABELS.get(value, value)


def media_consent_label(value: bool | None) -> str:
    if value is True:
        return "Так"
    if value is False:
        return "Ні"
    return "Не зазначено"


NUMBER_TO_CODE = {n: code for n, code, _ in VULNERABILITY_OPTIONS}
CODE_TO_LABEL = {code: label for _, code, label in VULNERABILITY_OPTIONS}


def vulnerability_prompt() -> str:
    lines = [
        "🧩 <b>Соціальний статус / категорії вразливості</b>",
        "",
        "Це обов’язковий крок реєстрації. Дані використовуються лише для внутрішньої аналітики та коректного планування підтримки. Якщо не хочете повідомляти категорію — оберіть 0. Якщо не належите до жодної з перелічених категорій — оберіть 13.",
        "",
        "Можна обрати <b>декілька</b> варіантів. Напишіть номери через кому, наприклад: <code>1,4,7</code>.",
        "",
        "0 — Не бажаю зазначати",
    ]
    lines.extend(f"{n} — {label}" for n, _, label in VULNERABILITY_OPTIONS)
    return "\n".join(lines)


def parse_vulnerability_numbers(raw: str) -> tuple[list[str], bool]:
    text = (raw or "").strip().replace(";", ",")
    if not text:
        raise ValueError("Порожня відповідь")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    try:
        nums = [int(p) for p in parts]
    except ValueError as exc:
        raise ValueError("Використовуйте лише номери через кому") from exc
    if 0 in nums:
        if len(set(nums)) > 1:
            raise ValueError("0 («Не бажаю зазначати») не можна поєднувати з іншими варіантами")
        return [], False
    if 13 in nums and len(set(nums)) > 1:
        raise ValueError("13 («Не відношусь до жодної категорії») не можна поєднувати з іншими варіантами")
    invalid = [n for n in nums if n not in NUMBER_TO_CODE]
    if invalid:
        raise ValueError(f"Невідомі номери: {', '.join(map(str, invalid))}")
    codes: list[str] = []
    for n in nums:
        code = NUMBER_TO_CODE[n]
        if code not in codes:
            codes.append(code)
    return codes, "other" in codes


def dump_vulnerabilities(codes: list[str], other_text: str | None = None) -> str:
    payload = {"codes": codes, "other": (other_text or "").strip()}
    return json.dumps(payload, ensure_ascii=False)


def load_vulnerabilities(raw: str | None) -> tuple[list[str], str]:
    if not raw:
        return [], ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            codes = [str(x) for x in data.get("codes", []) if str(x) in CODE_TO_LABEL]
            other = str(data.get("other") or "").strip()
            return codes, other
        if isinstance(data, list):
            return [str(x) for x in data if str(x) in CODE_TO_LABEL], ""
    except (json.JSONDecodeError, TypeError):
        pass
    # Compatibility with any simple comma-separated legacy values.
    codes = [x.strip() for x in raw.split(",") if x.strip() in CODE_TO_LABEL]
    return codes, ""


def vulnerability_labels(raw: str | None) -> list[str]:
    codes, other = load_vulnerabilities(raw)
    labels = [CODE_TO_LABEL[c] for c in codes if c != "other"]
    if "other" in codes:
        labels.append(f"Інша категорія: {other}" if other else "Інша категорія")
    return labels
