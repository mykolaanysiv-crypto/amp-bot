from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RegistrationJourney

REGISTRATION_STEPS = (
    "privacy_notice",
    "last_name",
    "first_name",
    "phone",
    "email",
    "settlement",
    "birth_date",
    "gender",
    "vulnerabilities",
    "media_consent",
)


def registration_progress(step: str) -> str:
    normalized = "vulnerabilities" if step == "vulnerability_other" else step
    try:
        idx = REGISTRATION_STEPS.index(normalized) + 1
    except ValueError:
        idx = 1
    total = len(REGISTRATION_STEPS)
    filled = round(idx / total * 8)
    bar = "█" * filled + "░" * (8 - filled)
    return f"📝 <b>Крок {idx} із {total}</b> · {bar}"


def _fernet(secret: str) -> Fernet:
    # Separate cryptographic context from cookies/sessions while allowing the
    # already-required production WEB_SESSION_SECRET to act as the root secret.
    digest = hashlib.sha256((secret + "|AMP-registration-draft-v1").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_draft(secret: str, data: dict[str, Any]) -> str:
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    raw = json.dumps(clean, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return _fernet(secret).encrypt(raw).decode("ascii")


def decrypt_draft(secret: str, ciphertext: str | None) -> dict[str, Any]:
    if not ciphertext:
        return {}
    try:
        raw = _fernet(secret).decrypt(ciphertext.encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (InvalidToken, ValueError, json.JSONDecodeError):
        return {}


async def get_registration_journey(session: AsyncSession, tg_id: int) -> RegistrationJourney | None:
    return await session.scalar(select(RegistrationJourney).where(RegistrationJourney.tg_id == tg_id))


async def save_registration_checkpoint(
    session: AsyncSession,
    *,
    tg_id: int,
    step: str,
    data: dict[str, Any],
    secret: str,
    start_payload: str = "",
    mark_consent: bool = False,
    mark_profile: bool = False,
) -> RegistrationJourney:
    now = datetime.utcnow()
    row = await get_registration_journey(session, tg_id)
    if not row:
        row = RegistrationJourney(tg_id=tg_id, started_at=now)
        session.add(row)
        await session.flush()
    row.current_step = step
    row.start_payload = (start_payload or row.start_payload or "")[:180]
    row.draft_ciphertext = encrypt_draft(secret, data)
    row.updated_at = now
    if mark_consent and not row.consent_at:
        row.consent_at = now
    if mark_profile and not row.profile_at:
        row.profile_at = now
    return row


async def restart_registration_journey(session: AsyncSession, tg_id: int, *, start_payload: str = "") -> RegistrationJourney:
    now = datetime.utcnow()
    row = await get_registration_journey(session, tg_id)
    if not row:
        row = RegistrationJourney(tg_id=tg_id, started_at=now)
        session.add(row)
        await session.flush()
    else:
        row.restarted_count = int(row.restarted_count or 0) + 1
        row.started_at = now
    row.current_step = "privacy_notice"
    row.draft_ciphertext = ""
    row.start_payload = (start_payload or "")[:180]
    row.consent_at = None
    row.profile_at = None
    row.submitted_at = None
    row.approved_at = None
    row.first_activity_at = None
    row.user_id = None
    row.updated_at = now
    return row


async def mark_registration_submitted(session: AsyncSession, tg_id: int, user_id: int) -> None:
    row = await get_registration_journey(session, tg_id)
    if not row:
        row = RegistrationJourney(tg_id=tg_id)
        session.add(row)
    now = datetime.utcnow()
    row.user_id = user_id
    row.current_step = "submitted"
    row.draft_ciphertext = ""  # questionnaire now lives only in the normalized User record
    row.submitted_at = row.submitted_at or now
    row.updated_at = now


async def mark_registration_approved(session: AsyncSession, user_id: int) -> None:
    row = await session.scalar(select(RegistrationJourney).where(RegistrationJourney.user_id == user_id))
    if not row:
        return
    row.approved_at = row.approved_at or datetime.utcnow()
    row.current_step = "approved"
    row.updated_at = datetime.utcnow()


async def mark_first_activity(session: AsyncSession, user_id: int, at: datetime | None = None) -> None:
    row = await session.scalar(select(RegistrationJourney).where(RegistrationJourney.user_id == user_id))
    if not row or row.first_activity_at:
        return
    row.first_activity_at = at or datetime.utcnow()
    row.current_step = "first_activity"
    row.updated_at = row.first_activity_at


async def registration_funnel_counts(session: AsyncSession) -> dict[str, int]:
    # Funnel columns are timestamps only; no personal registration answers are read.
    return {
        "start": int(await session.scalar(select(func.count(RegistrationJourney.id))) or 0),
        "consent": int(await session.scalar(select(func.count(RegistrationJourney.id)).where(RegistrationJourney.consent_at.is_not(None))) or 0),
        "profile": int(await session.scalar(select(func.count(RegistrationJourney.id)).where(RegistrationJourney.profile_at.is_not(None))) or 0),
        "submit": int(await session.scalar(select(func.count(RegistrationJourney.id)).where(RegistrationJourney.submitted_at.is_not(None))) or 0),
        "approved": int(await session.scalar(select(func.count(RegistrationJourney.id)).where(RegistrationJourney.approved_at.is_not(None))) or 0),
        "first_activity": int(await session.scalar(select(func.count(RegistrationJourney.id)).where(RegistrationJourney.first_activity_at.is_not(None))) or 0),
    }
