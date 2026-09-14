from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

AMBASSADOR_ROLES = {
    UserRole.AMBASSADOR.value,
    UserRole.COORDINATOR.value,
    UserRole.ADMIN.value,
    UserRole.SUPERADMIN.value,
}


def _jar_send_id(jar_url: str) -> str:
    return (jar_url or "").rstrip("/").split("/")[-1].strip()


def _api_get(path: str, token: str) -> Any:
    req = Request(
        f"{MONOBANK_API}{path}",
        headers={"X-Token": token, "User-Agent": "AMPasadors/1.10.4"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=15) as response:  # noqa: S310 - fixed Monobank host
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"Monobank API: HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Monobank API недоступний: {exc}") from exc


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
        state.updated_at = datetime.utcnow()
        return {"ok": False, "imported": 0, "linked": 0, "awarded": {}, "error": state.last_error}

    send_id = _jar_send_id(getattr(settings, "donation_jar_url", ""))
    try:
        client = await asyncio.to_thread(_api_get, "/personal/client-info", token)
        jars = client.get("jars") or [] if isinstance(client, dict) else []
        jar = next((item for item in jars if str(item.get("sendId") or "") == send_id), None)
        if not jar:
            raise RuntimeError("Налаштовану банку не знайдено серед банок власника MONOBANK_TOKEN.")
        jar_id = str(jar.get("id") or "").strip()
        if not jar_id:
            raise RuntimeError("Monobank не повернув ідентифікатор банки.")

        state.jar_account_id = jar_id
        state.send_id = send_id
        state.title = str(jar.get("title") or "Підтримка АМП")[:180]
        state.balance_kop = int(jar.get("balance") or 0)
        state.goal_kop = int(jar.get("goal") or 0)

        latest = await session.scalar(select(func.max(DonationTransaction.occurred_at)))
        # Re-read a small overlap to make eventual consistency harmless; provider IDs de-duplicate rows.
        start = (latest - timedelta(days=1)) if latest else (datetime.utcnow() - timedelta(days=31))
        earliest = datetime.utcnow() - timedelta(days=31)
        if start < earliest:
            start = earliest
        now = datetime.utcnow()
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
                # Preserve a manually linked participant while refreshing descriptive fields.
                row.description = str(item.get("description") or row.description or "")
                row.comment = str(item.get("comment") or row.comment or "")
                row.counter_name = str(item.get("counterName") or row.counter_name or "") or None
                row.receipt_id = str(item.get("receiptId") or row.receipt_id or "") or None
                continue
            occurred = datetime.utcfromtimestamp(int(item.get("time") or int(now.timestamp())))
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

        awarded: dict[int, list[str]] = {}
        for user_id in sorted(affected_users):
            badges = await award_donation_badges(session, user_id)
            if badges:
                awarded[user_id] = [b.name for b in badges]

        state.last_sync_at = datetime.utcnow()
        state.last_error = None
        state.updated_at = datetime.utcnow()
        return {"ok": True, "imported": imported, "linked": linked, "awarded": awarded, "error": None}
    except Exception as exc:
        state.last_error = str(exc)[:1000]
        state.updated_at = datetime.utcnow()
        return {"ok": False, "imported": 0, "linked": 0, "awarded": {}, "error": state.last_error}
