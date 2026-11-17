"""Reward exchange history, separate from earned XP and seasonal level XP.

Reward purchases affect the spendable wallet, not lifetime XP. Existing
RewardClaim rows remain the legacy source for transactions made before this
audit trail was introduced. AuditLog retains every subsequent repeat purchase,
even when a repeatable service reuses the same RewardClaim.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select

from .domain_services import log_audit
from .model_domains import AuditLog, Reward, RewardClaim, XPTransaction


REWARD_EVENT_ACTIONS = (
    "reward_spent",
    "reward_refunded",
    "reward_fulfilled",
    "reward_streak_restored",
)
REWARD_VISIBLE_ACTIONS = (*REWARD_EVENT_ACTIONS, "telegram_streak_restore_reward")

REWARD_EVENT_LABELS = {
    "reward_spent": "Обміняно на винагороду",
    "reward_refunded": "Повернено XP",
    "reward_fulfilled": "Винагороду видано",
    "reward_streak_restored": "Відновлено суперсерію",
}


async def record_reward_event(
    session, action: str, *, user, reward, claim_id: int | None = None,
    xp_delta: int = 0, processed_by: str = "",
):
    """Write one auditable reward event in the same DB transaction as the wallet."""
    if action not in REWARD_EVENT_ACTIONS:
        raise ValueError(f"Unknown reward event: {action}")
    payload = {
        "reward_id": reward.id,
        "reward_title": reward.title,
        "claim_id": claim_id,
        "xp_delta": int(xp_delta),
        "wallet_after": int(user.wallet_xp or 0),
        "processed_by": processed_by,
    }
    return await log_audit(
        session, action, actor=user,
        entity_type="reward_claim" if claim_id is not None else "reward",
        entity_id=claim_id if claim_id is not None else reward.id,
        details=json.dumps(payload, ensure_ascii=False),
    )


async def preserve_legacy_claim_before_reuse(session, *, claim, user, reward) -> None:
    """Retain the last pre-upgrade service purchase before its claim is reused."""
    exists = await session.scalar(
        select(AuditLog.id).where(
            AuditLog.action == "reward_spent",
            AuditLog.entity_type == "reward_claim",
            AuditLog.entity_id == claim.id,
        ).limit(1)
    )
    if exists:
        return
    spent = await record_reward_event(
        session, "reward_spent", user=user, reward=reward,
        claim_id=claim.id, xp_delta=-int(claim.xp_spent or 0),
        processed_by="Історичний запис до оновлення",
    )
    spent.created_at = claim.requested_at
    details = json.loads(spent.details)
    details["wallet_after"] = None  # The old balance was never recorded.
    spent.details = json.dumps(details, ensure_ascii=False)
    if claim.status == "fulfilled" and claim.fulfilled_at:
        fulfilled = await record_reward_event(
            session, "reward_fulfilled", user=user, reward=reward,
            claim_id=claim.id,
            processed_by="Історичний запис до оновлення",
        )
        fulfilled.created_at = claim.fulfilled_at
        details = json.loads(fulfilled.details)
        details["wallet_after"] = None
        fulfilled.details = json.dumps(details, ensure_ascii=False)


def decode_reward_event(row) -> dict | None:
    if row.action == "telegram_streak_restore_reward":
        # Legacy restoration was logged only as human-readable text.
        match = re.search(r"списано\s+(\d+)\s+XP", row.details or "", re.I)
        if not match:
            return None
        return {
            "at": row.created_at, "event_id": row.id,
            "user_id": row.actor_user_id, "action": row.action,
            "status": "Відновлено суперсерію",
            "reward_title": "Відновлення суперсерії",
            "reward_id": row.entity_id, "claim_id": None,
            "delta": -int(match.group(1)), "balance_after": None,
            "processed_by": "",
        }
    if row.action not in REWARD_EVENT_ACTIONS:
        return None
    try:
        payload = json.loads(row.details or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        delta = int(payload.get("xp_delta") or 0)
    except (TypeError, ValueError):
        return None
    return {
        "at": row.created_at,
        "event_id": row.id,
        "user_id": row.actor_user_id,
        "action": row.action,
        "status": REWARD_EVENT_LABELS[row.action],
        "reward_title": str(payload.get("reward_title") or "Винагорода"),
        "reward_id": payload.get("reward_id"),
        "claim_id": payload.get("claim_id"),
        "delta": delta,
        "balance_after": payload.get("wallet_after"),
        "processed_by": str(payload.get("processed_by") or ""),
    }


async def reward_operations_for_user(session, user_id: int, *, limit: int = 200) -> list[dict]:
    """Unified XP/expense timeline, without reducing lifetime XP for purchases."""
    txs = list((await session.scalars(
        select(XPTransaction).where(XPTransaction.user_id == user_id)
        .order_by(XPTransaction.created_at.desc(), XPTransaction.id.desc()).limit(limit)
    )).all())
    claims = list((await session.execute(
        select(RewardClaim, Reward)
        .join(Reward, Reward.id == RewardClaim.reward_id)
        .where(RewardClaim.user_id == user_id)
        .order_by(RewardClaim.requested_at.desc(), RewardClaim.id.desc()).limit(limit)
    )).all())
    audit_rows = list((await session.scalars(
        select(AuditLog).where(
            AuditLog.actor_user_id == user_id,
            AuditLog.action.in_(REWARD_VISIBLE_ACTIONS),
        ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    )).all())

    result = [
        {
            "at": tx.created_at, "delta": int(tx.amount or 0),
            "category": "Нарахування / коригування",
            "detail": tx.description or tx.category or "XP-операція",
            "balance_after": None,
            "event_type": "xp",
        }
        for tx in txs
    ]
    spent_claim_ids: set[int] = set()
    refunded_claim_ids: set[int] = set()
    new_refunds_by_claim: dict[int, list] = {}
    for log in audit_rows:
        event = decode_reward_event(log)
        if event:
            if event["action"] == "reward_spent" and event["claim_id"] is not None:
                spent_claim_ids.add(int(event["claim_id"]))
            if event["action"] == "reward_refunded" and event["claim_id"] is not None:
                refunded_claim_ids.add(int(event["claim_id"]))
                new_refunds_by_claim.setdefault(int(event["claim_id"]), []).append(event["at"])
            if event["action"] == "reward_fulfilled":
                continue  # Fulfilment changes status, not the XP balance.
            result.append({
                "at": event["at"], "delta": event["delta"],
                "category": "Повернення XP" if event["delta"] > 0 else "Витрата XP",
                "detail": f'{event["status"]}: {event["reward_title"]}',
                "balance_after": event["balance_after"],
                "event_type": "reward",
            })

    # Earlier web rejections were audit-logged without an explicit wallet row.
    # Recover their actual timestamp; newly logged refunds are deduplicated.
    claim_by_id = {claim.id: (claim, reward) for claim, reward in claims}
    if claim_by_id:
        old_refunds = list((await session.scalars(
            select(AuditLog).where(
                AuditLog.action == "web_reward_reject",
                AuditLog.entity_type == "reward_claim",
                AuditLog.entity_id.in_(claim_by_id),
            ).order_by(AuditLog.created_at.desc()).limit(limit)
        )).all())
        for old_refund in old_refunds:
            claim, reward = claim_by_id[int(old_refund.entity_id)]
            if any(
                abs((old_refund.created_at - fresh_at).total_seconds()) < 60
                for fresh_at in new_refunds_by_claim.get(claim.id, [])
            ):
                continue
            refunded_claim_ids.add(claim.id)
            historic_amount = re.search(r"xp=(\d+)", old_refund.details or "")
            result.append({
                "at": old_refund.created_at,
                "delta": int(historic_amount.group(1)) if historic_amount else int(claim.xp_spent or 0),
                "category": "Повернення XP",
                "detail": f"Відхилено заявку: {reward.title}",
                "balance_after": None, "event_type": "reward",
            })

    for claim, reward in claims:
        if claim.id not in spent_claim_ids:
            title = reward.title
            detail = f"Обміняно на винагороду: {title}"
            if claim.status == "rejected" and claim.id not in refunded_claim_ids:
                detail += " (заявку відхилено, XP повернуто; дата повернення невідома)"
            result.append({
                "at": claim.requested_at, "delta": -int(claim.xp_spent or 0),
                "category": "Витрата XP", "detail": detail,
                "balance_after": None, "event_type": "reward",
            })

    return sorted(
        (row for row in result if row["at"] is not None),
        key=lambda row: row["at"], reverse=True,
    )[:limit]
