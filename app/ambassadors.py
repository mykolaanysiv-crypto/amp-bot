from __future__ import annotations

AMBASSADOR_RESPONSIBILITIES: tuple[str, ...] = (
    "Спортзал",
    "Івент-зал",
    "Бібліотека",
    "Подкаст-студія",
    "Музична кімната",
    "Настільні ігри",
    "Кухня",
    "Внутрішній дворик",
)


def responsibility_label(value: str | None) -> str:
    clean = (value or "").strip()
    return clean if clean in AMBASSADOR_RESPONSIBILITIES else "Не визначено"
