from __future__ import annotations

from .time_utils import clock

import json
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from .model_domains import SettlementReference, User
from .observability import log_extra

# v1.10.3 canonical directory.  The list is deliberately conservative: only
# names already used by AMP are seeded.  Other legitimate settlements are
# learned from existing/user-entered values and added to the directory rather
# than silently rewritten to an invented locality.
DEFAULT_SETTLEMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Анисів", ("Анисiв", "с.Анисів", "с. Анисів", "село Анисів", "с Анисів")),
    ("Іванівка", ("с.Іванівка", "с. Іванівка", "село Іванівка", "с Іванівка")),
    ("Бакланова Муравійка", ("с.Бакланова Муравійка", "с. Бакланова Муравійка")),
    ("Васильків", ("с.Васильків", "с. Васильків")),
    ("Лукашівка", ("с.Лукашівка", "с. Лукашівка")),
)

_PREFIX_RE = re.compile(r"^(?:село|смт|с\.)\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def clean_settlement(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _SPACE_RE.sub(" ", text)
    return text or None


def settlement_key(value: str | None) -> str:
    """Stable comparison key for spelling/prefix duplicates.

    We intentionally fix only high-confidence Cyrillic/Latin confusables found
    in the current AMP data.  This avoids aggressive transliteration that could
    merge distinct foreign place names.
    """
    text = clean_settlement(value) or ""
    text = _PREFIX_RE.sub("", text).strip()
    text = text.translate(str.maketrans({"i": "і", "I": "і", "ı": "і"}))
    return text.casefold()


def canonicalize_settlement_text(value: str | None) -> str | None:
    cleaned = clean_settlement(value)
    if not cleaned:
        return None
    key = settlement_key(cleaned)
    for canonical, aliases in DEFAULT_SETTLEMENTS:
        if key == settlement_key(canonical) or any(key == settlement_key(alias) for alias in aliases):
            return canonical
    # For unknown legitimate locations preserve the user's spelling (apart from
    # whitespace cleanup); they become canonical directory entries later.
    return cleaned


def _aliases(row: SettlementReference) -> list[str]:
    try:
        data = json.loads(row.aliases_json or "[]")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logging.getLogger("amp.settlements").warning(
            "Некоректний aliases_json у довіднику населених пунктів",
            extra=log_extra("SETTLEMENT_ALIASES_JSON_INVALID", settlement_id=getattr(row, "id", None), exception_type=type(exc).__name__),
        )
        return []
    return [str(x) for x in data if str(x).strip()] if isinstance(data, list) else []


async def ensure_settlement_directory(session: AsyncSession) -> int:
    """Seed the directory and normalize existing profiles idempotently.

    Returns the number of user profiles whose value changed.  Existing unknown
    settlements are preserved and added as canonical entries.
    """
    now = clock.storage_utc()
    rows = list((await session.scalars(select(SettlementReference))).all())
    by_key: dict[str, SettlementReference] = {}
    for row in rows:
        by_key[settlement_key(row.canonical_name)] = row
        for alias in _aliases(row):
            by_key.setdefault(settlement_key(alias), row)

    for order, (canonical, aliases) in enumerate(DEFAULT_SETTLEMENTS, start=10):
        row = by_key.get(settlement_key(canonical))
        if not row:
            try:
                async with session.begin_nested():
                    row = SettlementReference(
                        canonical_name=canonical,
                        aliases_json=json.dumps(list(aliases), ensure_ascii=False),
                        active=True,
                        sort_order=order,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    await session.flush()
            except IntegrityError:
                # Bot and web may bootstrap at nearly the same time. Reuse the
                # row created by the other process instead of failing startup.
                row = await session.scalar(select(SettlementReference).where(SettlementReference.canonical_name == canonical))
                if not row:
                    raise
        if row:
            merged = list(dict.fromkeys([*_aliases(row), *aliases]))
            row.aliases_json = json.dumps(merged, ensure_ascii=False)
            row.updated_at = now
        by_key[settlement_key(canonical)] = row
        for alias in aliases:
            by_key[settlement_key(alias)] = row

    changed = 0
    users = list((await session.scalars(select(User).where(User.settlement.is_not(None), User.settlement != ""))).all())
    for user in users:
        raw = clean_settlement(user.settlement)
        if not raw:
            continue
        key = settlement_key(raw)
        row = by_key.get(key)
        if row:
            canonical = row.canonical_name
        else:
            canonical = canonicalize_settlement_text(raw) or raw
            row = by_key.get(settlement_key(canonical))
            if not row:
                row = SettlementReference(
                    canonical_name=canonical,
                    aliases_json="[]",
                    active=True,
                    sort_order=1000,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                await session.flush()
            by_key[settlement_key(canonical)] = row
        if user.settlement != canonical:
            user.settlement = canonical
            changed += 1
    return changed


async def resolve_canonical_settlement(session: AsyncSession, value: str | None) -> str | None:
    cleaned = canonicalize_settlement_text(value)
    if not cleaned:
        return None
    rows = list((await session.scalars(select(SettlementReference).where(SettlementReference.active == True))).all())  # noqa: E712
    key = settlement_key(cleaned)
    for row in rows:
        if key == settlement_key(row.canonical_name) or any(key == settlement_key(alias) for alias in _aliases(row)):
            return row.canonical_name
    # A legitimate new place is added to the directory and becomes its own
    # canonical value instead of remaining free text outside the dictionary.
    try:
        async with session.begin_nested():
            row = SettlementReference(canonical_name=cleaned, aliases_json="[]", active=True, sort_order=1000)
            session.add(row)
            await session.flush()
    except IntegrityError as exc:
        # A concurrent request may have inserted it first. The nested transaction
        # keeps the caller's surrounding transaction usable, and the conflict is
        # visible in structured logs instead of being silently swallowed.
        logging.getLogger("amp.settlements").info(
            "Concurrent settlement insert reused existing row",
            extra=log_extra("SETTLEMENT_CONCURRENT_INSERT", settlement=cleaned, exception_type=type(exc).__name__),
        )
    return cleaned


async def settlement_quality_report(session: AsyncSession) -> dict:
    refs = list((await session.scalars(select(SettlementReference).where(SettlementReference.active == True))).all())  # noqa: E712
    users = list((await session.scalars(select(User).where(User.settlement.is_not(None), User.settlement != ""))).all())
    canonical_names = {row.canonical_name for row in refs}
    ref_keys = {settlement_key(row.canonical_name): row.canonical_name for row in refs}
    for row in refs:
        for alias in _aliases(row):
            ref_keys[settlement_key(alias)] = row.canonical_name

    raw_groups: dict[str, set[str]] = defaultdict(set)
    missing: list[str] = []
    for user in users:
        raw = clean_settlement(user.settlement)
        if not raw:
            continue
        raw_groups[settlement_key(raw)].add(raw)
        if raw not in canonical_names:
            expected = ref_keys.get(settlement_key(raw))
            if expected != raw:
                missing.append(raw)

    duplicate_groups = [sorted(values) for values in raw_groups.values() if len(values) > 1]

    # Also surface likely typo-created canonical duplicates. Unknown legitimate
    # settlements are allowed, so this is intentionally conservative: similar
    # spelling, same initial, and almost equal length. We only *flag* them; an
    # administrator decides whether they are truly the same place.
    canonical_values = sorted({clean_settlement(row.canonical_name) for row in refs if clean_settlement(row.canonical_name)})
    seen_pairs: set[tuple[str, str]] = set()
    for idx, left in enumerate(canonical_values):
        lk = settlement_key(left)
        for right in canonical_values[idx + 1:]:
            rk = settlement_key(right)
            if not lk or not rk or lk == rk or lk[:1] != rk[:1] or abs(len(lk) - len(rk)) > 2:
                continue
            if SequenceMatcher(None, lk, rk).ratio() >= 0.82:
                pair = tuple(sorted((left, right)))
                if pair not in seen_pairs:
                    duplicate_groups.append(list(pair))
                    seen_pairs.add(pair)

    # Deduplicate groups produced by raw profile values and directory similarity.
    unique_groups: list[list[str]] = []
    group_keys: set[tuple[str, ...]] = set()
    for group in duplicate_groups:
        key = tuple(sorted(dict.fromkeys(group)))
        if len(key) > 1 and key not in group_keys:
            group_keys.add(key)
            unique_groups.append(list(key))

    return {
        "directory_count": len(refs),
        "profiles_with_settlement": len(users),
        "duplicate_groups": unique_groups,
        "duplicate_count": len(unique_groups),
        "noncanonical_values": sorted(set(missing)),
        "noncanonical_count": len(set(missing)),
    }
