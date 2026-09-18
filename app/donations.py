from __future__ import annotations

from .time_utils import UTC, clock

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .version import APP_VERSION
from .models import Badge, DonationJarState, DonationTransaction, User, UserBadge, UserRole

MONOBANK_API = "https://api.monobank.ua"
AMP_ID_RE = re.compile(r"(?:АМП|AMP)[\s\-#:]*(\d{1,8})", re.IGNORECASE)

DONATION_BADGES: tuple[dict[str, Any], ...] = (
    {
        "name": "Мій перший донат",
        "icon": "💙",
        "description": "Перший підтверджений донат на підтримку АМП від 50 грн.",
        "criteria_type": "donation_first",
        "criteria_value": 5000,
        "badge_type": "general",
    },
    {
        "name": "Мажор",
        "icon": "💸",
        "description": "Разовий донат на підтримку АМП від 200 грн.",
        "criteria_type": "donation_single",
        "criteria_value": 20000,
        "badge_type": "general",
    },
    {
        "name": "Мафіозі",
        "icon": "🎩",
        "description": "Разовий донат на підтримку АМП від 500 грн.",
        "criteria_type": "donation_single",
        "criteria_value": 50000,
        "badge_type": "general",
    },
    {
        "name": "Меценат",
        "icon": "🤝",
        "description": "Разовий донат на підтримку АМП від 1000 грн.",
        "criteria_type": "donation_single",
        "criteria_value": 100000,
        "badge_type": "general",
    },
    {
        "name": "Почесний спонсор АМП",
        "icon": "🌟",
        "description": "Сумарна підтримка АМП перевищила 2000 грн.",
        "criteria_type": "donation_total_over",
        "criteria_value": 200000,
        "badge_type": "general",
    },
    {
        "name": "Брюс Всемогутній",
        "icon": "⚡",
        "description": "Ексклюзивний бейдж АМПасадора за сумарну підтримку АМП понад 5000 грн.",
        "criteria_type": "donation_total_over",
        "criteria_value": 500000,
        "badge_type": "ambassador",
    },
)


DONATION_XP_KOP_PER_POINT = 500  # 5 UAH = 1 XP


def donation_xp_for_amount(amount_kop: int) -> int:
    """Return earned XP for a positive UAH donation at the canonical 5 UAH/XP rate."""
    return max(0, int(amount_kop or 0) // DONATION_XP_KOP_PER_POINT)


async def award_donation_xp_for_transaction(session: AsyncSession, row: DonationTransaction) -> int:
    """Idempotently award XP for one linked Monobank transaction."""
    if not row.linked_user_id or int(row.currency_code or 980) != 980 or int(row.amount_kop or 0) <= 0:
        return 0
    xp = donation_xp_for_amount(int(row.amount_kop or 0))
    if xp <= 0:
        return 0
    marker = f"donation:{row.provider_transaction_id}"
    from .models import XPTransaction
    exists = await session.scalar(select(XPTransaction.id).where(
        XPTransaction.user_id == row.linked_user_id,
        XPTransaction.category == "donation",
        XPTransaction.description.contains(marker),
    ))
    if exists:
        return 0
    user = await session.get(User, row.linked_user_id)
    if not user:
        return 0
    from .domain_services.gamification import add_xp
    amount_uah = int(row.amount_kop or 0) / 100
    await add_xp(
        session, user, xp,
        f"Донат {amount_uah:g} грн · 1 XP = 5 грн · {marker}",
        category="donation",
    )
    return xp


async def auto_link_existing_donations(session: AsyncSession) -> int:
    """Link historical local ledger rows that already contain an AMP code."""
    rows = list((await session.scalars(select(DonationTransaction).where(
        DonationTransaction.linked_user_id.is_(None),
        DonationTransaction.amount_kop > 0,
        DonationTransaction.currency_code == 980,
    ))).all())
    linked = 0
    for row in rows:
        payload = {"comment": row.comment, "description": row.description, "counterName": row.counter_name}
        user_id = await _auto_link_user(session, payload)
        if user_id:
            row.linked_user_id = user_id
            linked += 1
    if linked:
        await session.flush()
    return linked


async def backfill_donation_xp(session: AsyncSession) -> dict[int, int]:
    """Award all missing donation XP, including donations imported before this release."""
    rows = list((await session.scalars(select(DonationTransaction).where(
        DonationTransaction.linked_user_id.is_not(None),
        DonationTransaction.amount_kop > 0,
        DonationTransaction.currency_code == 980,
    ).order_by(DonationTransaction.occurred_at.asc(), DonationTransaction.id.asc()))).all())
    awarded: dict[int, int] = {}
    for row in rows:
        xp = await award_donation_xp_for_transaction(session, row)
        if xp:
            awarded[int(row.linked_user_id)] = awarded.get(int(row.linked_user_id), 0) + xp
    return awarded

AMBASSADOR_ROLES = {
    UserRole.AMBASSADOR.value,
    UserRole.COORDINATOR.value,
    UserRole.ADMIN.value,
    UserRole.SUPERADMIN.value,
}


def _normalize_jar_send_id(value: str) -> str:
    """Return the canonical public jar send id regardless of Monobank format.

    Monobank client-info currently returns values such as ``jar/5S531LWQuc``
    while the public URL ends with just ``5S531LWQuc``.  Keeping the comparison
    canonical prevents false "jar not found" errors when the provider includes
    the ``jar/`` prefix.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    return raw.split("/")[-1].strip()


def _jar_send_id(jar_url: str) -> str:
    return _normalize_jar_send_id(jar_url)


def _api_get(path: str, token: str) -> Any:
    req = Request(
        f"{MONOBANK_API}{path}",
        headers={"X-Token": token, "User-Agent": f"AMPasadors/{APP_VERSION}"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=15) as response:  # noqa: S310 - fixed Monobank host
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Never persist or display provider response bodies: they may contain
        # account metadata. Keep operational errors useful but data-minimized.
        if exc.code in {401, 403}:
            message = "Monobank API відхилив доступ. Перевірте MONOBANK_TOKEN у захищених змінних середовища."
        elif exc.code == 429:
            message = "Monobank API тимчасово обмежив частоту запитів. Повторіть синхронізацію пізніше."
        else:
            message = f"Monobank API тимчасово повернув HTTP {exc.code}."
        raise RuntimeError(message) from exc
    except (URLError, TimeoutError):
        raise RuntimeError("Monobank API тимчасово недоступний. Повторіть синхронізацію пізніше.")


async def ensure_donation_badges(session: AsyncSession) -> dict[str, Badge]:
    result: dict[str, Badge] = {}
    for spec in DONATION_BADGES:
        badge = await session.scalar(select(Badge).where(Badge.name == spec["name"]))
        if not badge:
            badge = Badge(
                name=spec["name"],
                icon=spec["icon"],
                description=spec["description"],
                criteria_type=spec["criteria_type"],
                criteria_value=int(spec["criteria_value"]),
                active=True,
                automatic=True,
                badge_type=spec["badge_type"],
            )
            session.add(badge)
            await session.flush()
        else:
            # Keep the built-in donor badges self-healing if a legacy row exists.
            badge.icon = spec["icon"]
            badge.description = spec["description"]
            badge.criteria_type = spec["criteria_type"]
            badge.criteria_value = int(spec["criteria_value"])
            badge.automatic = True
            badge.active = True
            badge.badge_type = spec["badge_type"]
        result[spec["name"]] = badge
    return result


async def donation_totals_for_user(session: AsyncSession, user_id: int) -> tuple[int, int, int]:
    amounts = list((await session.scalars(
        select(DonationTransaction.amount_kop).where(
            DonationTransaction.linked_user_id == user_id,
            DonationTransaction.amount_kop > 0,
            DonationTransaction.currency_code == 980,
        )
    )).all())
    positive = [int(v or 0) for v in amounts if int(v or 0) > 0]
    return sum(positive), max(positive, default=0), len(positive)


async def award_donation_badges(session: AsyncSession, user_id: int) -> list[Badge]:
    user = await session.get(User, user_id)
    if not user:
        return []
    badges = await ensure_donation_badges(session)
    total, largest, count = await donation_totals_for_user(session, user_id)
    if count <= 0:
        return []

    newly_awarded: list[Badge] = []
    for spec in DONATION_BADGES:
        badge = badges[spec["name"]]
        if badge.badge_type == "ambassador" and user.role not in AMBASSADOR_ROLES:
            continue
        threshold = int(spec["criteria_value"])
        if spec["criteria_type"] == "donation_first":
            qualifies = largest >= threshold
        elif spec["criteria_type"] == "donation_single":
            qualifies = largest >= threshold
        else:
            # User explicitly requested "more than" 2000 / 5000 for totals.
            qualifies = total > threshold
        if not qualifies:
            continue
        exists = await session.scalar(select(UserBadge).where(UserBadge.user_id == user_id, UserBadge.badge_id == badge.id))
        if exists:
            continue
        session.add(UserBadge(user_id=user_id, badge_id=badge.id, awarded_by=None))
        newly_awarded.append(badge)
    if newly_awarded:
        await session.flush()
    return newly_awarded


async def _auto_link_user(session: AsyncSession, payload: dict[str, Any]) -> int | None:
    haystack = " ".join(str(payload.get(key) or "") for key in ("comment", "description", "counterName"))
    match = AMP_ID_RE.search(haystack)
    if not match:
        return None
    user_id = int(match.group(1))
    return user_id if await session.get(User, user_id) else None


async def sync_monobank_donations(session: AsyncSession, settings) -> dict[str, Any]:
    """Synchronize the configured Monobank jar into the local audit-friendly ledger.

    The Personal Open API limits statement windows to roughly one month, so the
    first synchronization imports the latest 31 days. Future runs append new
    transactions and never overwrite local links to AMP participants.
    """
    state = await session.get(DonationJarState, 1)
    if not state:
        state = DonationJarState(id=1)
        session.add(state)
        await session.flush()

    token = (getattr(settings, "monobank_token", "") or "").strip()
    if not token:
        state.last_error = "Не задано MONOBANK_TOKEN. Банка доступна за посиланням, але автоматична синхронізація вимкнена."
        state.updated_at = clock.storage_utc()
        return {"ok": False, "imported": 0, "linked": 0, "awarded": {}, "xp_awarded": {}, "error": state.last_error}

    send_id = _jar_send_id(getattr(settings, "donation_jar_url", ""))
    try:
        client = await asyncio.to_thread(_api_get, "/personal/client-info", token)
        jars = client.get("jars") or [] if isinstance(client, dict) else []
        jar = next((item for item in jars if _normalize_jar_send_id(item.get("sendId")) == send_id), None)
        if not jar:
            raise RuntimeError("Налаштовану банку не знайдено серед банок власника MONOBANK_TOKEN.")
        jar_id = str(jar.get("id") or "").strip()
        if not jar_id:
            raise RuntimeError("Monobank не повернув ідентифікатор банки.")

        # The provider's internal jar account id is needed only for this API
        # request and is deliberately not persisted. The public send id is enough
        # for diagnostics without retaining an extra provider identifier.
        state.jar_account_id = None
        state.send_id = send_id
        state.title = str(jar.get("title") or "Підтримка АМП")[:180]
        state.balance_kop = int(jar.get("balance") or 0)
        state.goal_kop = int(jar.get("goal") or 0)

        latest = await session.scalar(select(func.max(DonationTransaction.occurred_at)))
        # Re-read a small overlap to make eventual consistency harmless; provider IDs de-duplicate rows.
        start = (latest - timedelta(days=1)) if latest else (clock.storage_utc() - timedelta(days=31))
        earliest = clock.storage_utc() - timedelta(days=31)
        if start < earliest:
            start = earliest
        now = clock.storage_utc()
        path = f"/personal/statement/{jar_id}/{int(start.timestamp())}/{int(now.timestamp())}"
        statement = await asyncio.to_thread(_api_get, path, token)
        if not isinstance(statement, list):
            raise RuntimeError("Monobank повернув некоректний формат виписки.")

        imported = 0
        linked = 0
        affected_users: set[int] = set()
        for item in statement:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            provider_id = str(item["id"])
            row = await session.scalar(select(DonationTransaction).where(DonationTransaction.provider_transaction_id == provider_id))
            if row:
                # Preserve a manual link, but allow older unlinked rows to be linked
                # automatically when an AMP code is present in the refreshed provider data.
                row.description = str(item.get("description") or row.description or "")
                row.comment = str(item.get("comment") or row.comment or "")
                row.counter_name = str(item.get("counterName") or row.counter_name or "") or None
                row.receipt_id = str(item.get("receiptId") or row.receipt_id or "") or None
                if not row.linked_user_id:
                    auto_user_id = await _auto_link_user(session, item)
                    if auto_user_id:
                        row.linked_user_id = auto_user_id
                        linked += 1
                        affected_users.add(auto_user_id)
                elif row.linked_user_id:
                    affected_users.add(int(row.linked_user_id))
                continue
            occurred = clock.storage_utc(datetime.fromtimestamp(int(item.get("time") or int(now.timestamp())), tz=UTC))
            auto_user_id = await _auto_link_user(session, item)
            row = DonationTransaction(
                provider_transaction_id=provider_id,
                occurred_at=occurred,
                amount_kop=int(item.get("amount") or 0),
                currency_code=int(item.get("currencyCode") or 980),
                description=str(item.get("description") or ""),
                comment=str(item.get("comment") or ""),
                counter_name=str(item.get("counterName") or "") or None,
                receipt_id=str(item.get("receiptId") or "") or None,
                linked_user_id=auto_user_id,
            )
            session.add(row)
            imported += 1
            if auto_user_id:
                linked += 1
                affected_users.add(auto_user_id)

        # Re-scan the already stored ledger too: donations imported by older
        # releases may contain an AMP code but still be unlinked.
        linked += await auto_link_existing_donations(session)
        # Backfill makes the release retroactive: every previously linked donation
        # that has not yet produced donation XP is rewarded exactly once.
        xp_awarded = await backfill_donation_xp(session)
        affected_users.update(xp_awarded.keys())

        awarded: dict[int, list[str]] = {}
        for user_id in sorted(affected_users):
            badges = await award_donation_badges(session, user_id)
            if badges:
                awarded[user_id] = [b.name for b in badges]

        state.last_sync_at = clock.storage_utc()
        state.last_error = None
        state.updated_at = clock.storage_utc()
        return {"ok": True, "imported": imported, "linked": linked, "awarded": awarded, "xp_awarded": xp_awarded, "error": None}
    except Exception as exc:
        # All expected API errors above are already sanitized. Do not include
        # repr(exc), request headers, tokens or provider response payloads.
        state.last_error = (str(exc) or "Помилка синхронізації Monobank.")[:500]
        state.updated_at = clock.storage_utc()
        return {"ok": False, "imported": 0, "linked": 0, "awarded": {}, "xp_awarded": {}, "error": state.last_error}
