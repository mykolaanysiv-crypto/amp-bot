from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
import re

from sqlalchemy import func, select

from .media import media_file
from .model_domains import (
    ActivityApplication, AuditLog, Base, Event, EventRegistration, MediaAsset, Opportunity,
    Quest, RequestCase, RequestMessage, Reward, RewardClaim, User, VolunteerTask,
    XPTransaction,
)
from .time_utils import clock

VALID_EVENT_REG_STATUSES = {
    "registered", "waitlisted", "reserved", "checked_in", "attended", "no_show", "cancelled"
}


@dataclass(slots=True)
class IntegrityIssue:
    code: str
    title: str
    category: str
    severity: str
    count: int
    detail: str
    samples: list[str]
    href: str = ""
    action: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _norm_phone(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _norm_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _norm_name(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _group_duplicates(users: list[User], extractor, *, minimum_len: int = 1) -> list[list[User]]:
    groups: dict[str, list[User]] = defaultdict(list)
    for user in users:
        key = extractor(user)
        if key and len(key) >= minimum_len:
            groups[key].append(user)
    return [rows for rows in groups.values() if len(rows) > 1]




def duplicate_match_reasons(left: User, right: User) -> list[str]:
    """Return conservative reasons why two participant profiles look duplicated."""
    reasons: list[str] = []
    left_phone, right_phone = _norm_phone(left.phone), _norm_phone(right.phone)
    if left_phone and right_phone and len(left_phone) >= 7 and left_phone == right_phone:
        reasons.append("phone")
    left_email, right_email = _norm_email(left.email), _norm_email(right.email)
    if left_email and right_email and left_email == right_email:
        reasons.append("email")
    if (
        left.birth_date
        and right.birth_date
        and left.birth_date == right.birth_date
        and _norm_name(left.full_name)
        and _norm_name(left.full_name) == _norm_name(right.full_name)
    ):
        reasons.append("name_birth")
    return reasons


def build_duplicate_groups(users: list[User]) -> list[dict]:
    """Build connected duplicate groups for safe manual review in the web center."""
    by_id = {u.id: u for u in users}
    parent = {u.id: u.id for u in users}
    reasons_by_root: dict[int, set[str]] = defaultdict(set)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int, reason: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            reasons_by_root[ra].update(reasons_by_root.pop(rb, set()))
        reasons_by_root[find(a)].add(reason)

    def connect(groups: list[list[User]], reason: str) -> None:
        for rows in groups:
            first = rows[0].id
            for row in rows[1:]:
                union(first, row.id, reason)

    connect(_group_duplicates(users, lambda u: _norm_phone(u.phone), minimum_len=7), "Однаковий телефон")
    connect(_group_duplicates(users, lambda u: _norm_email(u.email), minimum_len=3), "Однаковий email")
    profile_groups: dict[tuple[str, object], list[User]] = defaultdict(list)
    for u in users:
        if u.birth_date and _norm_name(u.full_name):
            profile_groups[(_norm_name(u.full_name), u.birth_date)].append(u)
    connect([rows for rows in profile_groups.values() if len(rows) > 1], "Однакові ПІБ + дата народження")

    components: dict[int, list[User]] = defaultdict(list)
    for uid, user in by_id.items():
        components[find(uid)].append(user)

    result: list[dict] = []
    for root, members in components.items():
        if len(members) < 2:
            continue
        member_ids = {m.id for m in members}
        reasons = set(reasons_by_root.get(find(root), set()))
        # Re-evaluate pair reasons after union so mixed phone/email components are described fully.
        ordered = sorted(members, key=lambda u: (u.created_at or clock.storage_utc(), u.id))
        for idx, left in enumerate(ordered):
            for right in ordered[idx + 1:]:
                for code in duplicate_match_reasons(left, right):
                    reasons.add({
                        "phone": "Однаковий телефон",
                        "email": "Однаковий email",
                        "name_birth": "Однакові ПІБ + дата народження",
                    }[code])
        result.append({
            "member_ids": sorted(member_ids),
            "reasons": sorted(reasons),
            "members": [
                {
                    "id": u.id,
                    "full_name": u.full_name,
                    "status": u.status,
                    "role": u.role,
                    "phone": u.phone,
                    "email": u.email,
                    "created_at": u.created_at,
                    "last_activity_at": u.last_activity_at,
                }
                for u in ordered
            ],
        })
    return sorted(result, key=lambda g: (-len(g["members"]), g["member_ids"]))


async def user_reference_summary(session, user_id: int) -> list[dict]:
    """Count direct FK references to a user across current SQLAlchemy metadata."""
    refs: list[dict] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            targets_user = any(
                fk.column.table.name == "users" and fk.column.name == "id"
                for fk in column.foreign_keys
            )
            if not targets_user:
                continue
            stmt = select(func.count()).select_from(table).where(column == user_id)
            if table.name == "users" and "id" in table.c:
                stmt = stmt.where(table.c.id != user_id)
            count = int(await session.scalar(stmt) or 0)
            if count:
                refs.append({"table": table.name, "column": column.name, "count": count})
    return refs

def _sample_user_groups(groups: list[list[User]], limit: int = 8) -> list[str]:
    samples: list[str] = []
    for group in groups[:limit]:
        samples.append(" / ".join(f"АМП-{u.id:04d} {u.full_name}" for u in group[:4]))
    return samples


async def _missing_media_samples(session, refs: list[tuple[str, int, str, str | None]], limit: int = 12) -> list[str]:
    db_ids = {
        int(path.rstrip("/").split("/")[-1])
        for _, _, _, path in refs
        if path and path.startswith("/media/") and path.rstrip("/").split("/")[-1].isdigit()
    }
    existing_db_ids: set[int] = set()
    if db_ids:
        existing_db_ids = set((await session.scalars(select(MediaAsset.id).where(MediaAsset.id.in_(db_ids)))).all())
    missing: list[str] = []
    for entity, entity_id, field_name, path in refs:
        if not path:
            continue
        ok = True
        if path.startswith("/media/"):
            tail = path.rstrip("/").split("/")[-1]
            ok = tail.isdigit() and int(tail) in existing_db_ids
        elif path.startswith(("/uploads/", "/private/")):
            ok = media_file(path) is not None
        if not ok:
            missing.append(f"{entity} #{entity_id}: {field_name} → {path}")
            if len(missing) >= limit:
                break
    return missing


async def scan_data_integrity(session) -> dict:
    now = clock.storage_utc()
    users = list((await session.scalars(select(User).where(User.permanent_deleted_at.is_(None)))).all())
    issues: list[IntegrityIssue] = []
    duplicate_groups = build_duplicate_groups(users)

    phone_groups = _group_duplicates(users, lambda u: _norm_phone(u.phone), minimum_len=7)
    if phone_groups:
        issues.append(IntegrityIssue(
            "duplicate_phone", "Дублікати телефонів", "Профілі", "high",
            sum(len(g) for g in phone_groups), "Один номер телефону використовується у кількох профілях.",
            _sample_user_groups(phone_groups), "/admin/users"
        ))

    email_groups = _group_duplicates(users, lambda u: _norm_email(u.email), minimum_len=3)
    if email_groups:
        issues.append(IntegrityIssue(
            "duplicate_email", "Дублікати email", "Профілі", "high",
            sum(len(g) for g in email_groups), "Одна email-адреса використовується у кількох профілях.",
            _sample_user_groups(email_groups), "/admin/users"
        ))

    profile_groups: dict[tuple[str, object], list[User]] = defaultdict(list)
    for u in users:
        if u.birth_date and _norm_name(u.full_name):
            profile_groups[(_norm_name(u.full_name), u.birth_date)].append(u)
    dup_profiles = [rows for rows in profile_groups.values() if len(rows) > 1]
    if dup_profiles:
        issues.append(IntegrityIssue(
            "duplicate_profile", "Ймовірні дублікати профілів", "Профілі", "medium",
            sum(len(g) for g in dup_profiles), "Збігаються ПІБ і дата народження. Потрібна ручна перевірка, автоматичного злиття немає.",
            _sample_user_groups(dup_profiles), "/admin/users"
        ))

    orphan_xp = int(await session.scalar(
        select(func.count(XPTransaction.id)).outerjoin(User, User.id == XPTransaction.user_id).where(User.id.is_(None))
    ) or 0)
    orphan_regs_user = int(await session.scalar(
        select(func.count(EventRegistration.id)).outerjoin(User, User.id == EventRegistration.user_id).where(User.id.is_(None))
    ) or 0)
    orphan_regs_event = int(await session.scalar(
        select(func.count(EventRegistration.id)).outerjoin(Event, Event.id == EventRegistration.event_id).where(Event.id.is_(None))
    ) or 0)
    orphan_claim_users = int(await session.scalar(
        select(func.count(RewardClaim.id)).outerjoin(User, User.id == RewardClaim.user_id).where(User.id.is_(None))
    ) or 0)
    orphan_claim_rewards = int(await session.scalar(
        select(func.count(RewardClaim.id)).outerjoin(Reward, Reward.id == RewardClaim.reward_id).where(Reward.id.is_(None))
    ) or 0)
    orphan_total = orphan_xp + orphan_regs_user + orphan_regs_event + orphan_claim_users + orphan_claim_rewards
    if orphan_total:
        issues.append(IntegrityIssue(
            "orphan_records", "Orphan records", "Зв’язки БД", "critical", orphan_total,
            "Записи посилаються на відсутні сутності. Видалення або переприв’язка — тільки після ручної перевірки.",
            [
                f"XP без user: {orphan_xp}", f"Реєстрації без user: {orphan_regs_user}",
                f"Реєстрації без event: {orphan_regs_event}", f"Reward claims без user: {orphan_claim_users}",
                f"Reward claims без reward: {orphan_claim_rewards}",
            ], "/admin/audit"
        ))

    lifetime_rows = (await session.execute(
        select(User.id, User.full_name, User.wallet_xp, func.coalesce(func.sum(XPTransaction.amount), 0))
        .outerjoin(XPTransaction, XPTransaction.user_id == User.id)
        .where(User.permanent_deleted_at.is_(None))
        .group_by(User.id)
    )).all()
    wallet_anomalies: list[str] = []
    for uid, name, wallet, lifetime in lifetime_rows:
        wallet_i, lifetime_i = int(wallet or 0), int(lifetime or 0)
        if wallet_i < 0 or wallet_i > max(0, lifetime_i):
            wallet_anomalies.append(f"АМП-{uid:04d} {name}: wallet={wallet_i}, lifetime={lifetime_i}")
    if wallet_anomalies:
        issues.append(IntegrityIssue(
            "wallet_xp_mismatch", "XP / wallet inconsistency", "XP та винагороди", "high", len(wallet_anomalies),
            "Spendable wallet не повинен бути від’ємним або перевищувати lifetime XP.",
            wallet_anomalies[:10], "/admin/users"
        ))

    bad_claims = list((await session.execute(
        select(RewardClaim.id, RewardClaim.user_id, RewardClaim.status, RewardClaim.xp_spent, RewardClaim.fulfilled_at)
        .where(
            (RewardClaim.xp_spent < 0)
            | ((RewardClaim.status == "fulfilled") & RewardClaim.fulfilled_at.is_(None))
            | ((RewardClaim.status != "fulfilled") & RewardClaim.fulfilled_at.is_not(None))
        )
        .limit(50)
    )).all())
    if bad_claims:
        issues.append(IntegrityIssue(
            "reward_claim_inconsistency", "Неконсистентні reward claims", "XP та винагороди", "high", len(bad_claims),
            "Статус, fulfilled_at або xp_spent суперечать очікуваному lifecycle винагороди.",
            [f"Claim #{r.id}: user={r.user_id}, status={r.status}, xp={r.xp_spent}" for r in bad_claims[:10]],
            "/admin/rewards"
        ))

    invalid_regs = list((await session.execute(
        select(EventRegistration.id, EventRegistration.event_id, EventRegistration.user_id, EventRegistration.status)
        .where(~EventRegistration.status.in_(VALID_EVENT_REG_STATUSES)).limit(100)
    )).all())
    if invalid_regs:
        issues.append(IntegrityIssue(
            "invalid_event_status", "Некоректні статуси реєстрацій", "Події", "high", len(invalid_regs),
            "Статус не входить до canonical event registration lifecycle.",
            [f"Reg #{r.id}: event={r.event_id}, user={r.user_id}, status={r.status}" for r in invalid_regs[:10]],
            "/admin/events"
        ))

    attendance_rows = list((await session.execute(
        select(EventRegistration.id, EventRegistration.event_id, EventRegistration.user_id, EventRegistration.status)
        .where(
            ((EventRegistration.status == "attended") & EventRegistration.confirmed_at.is_(None))
            | ((EventRegistration.status == "checked_in") & EventRegistration.checkin_at.is_(None))
            | ((EventRegistration.status == "no_show") & EventRegistration.no_show_at.is_(None))
        ).limit(100)
    )).all())
    future_attended = list((await session.execute(
        select(EventRegistration.id, EventRegistration.event_id, EventRegistration.user_id)
        .join(Event, Event.id == EventRegistration.event_id)
        .where(EventRegistration.status == "attended", Event.starts_at > clock.local_wall()).limit(100)
    )).all())
    if attendance_rows or future_attended:
        samples = [f"Reg #{r.id}: event={r.event_id}, user={r.user_id}, status={r.status}" for r in attendance_rows[:7]]
        samples += [f"Reg #{r.id}: майбутня подія #{r.event_id}, user={r.user_id}" for r in future_attended[:3]]
        issues.append(IntegrityIssue(
            "attendance_anomaly", "Attendance anomalies", "Події", "high", len(attendance_rows) + len(future_attended),
            "Timestamp/status не узгоджуються або attendance стоїть на майбутній події.", samples, "/admin/events"
        ))

    expired_reservations = list((await session.execute(
        select(EventRegistration.id, EventRegistration.event_id, EventRegistration.user_id, EventRegistration.reservation_expires_at)
        .where(
            EventRegistration.status == "reserved",
            EventRegistration.reservation_expires_at.is_not(None),
            EventRegistration.reservation_expires_at < now,
        ).limit(100)
    )).all())
    if expired_reservations:
        issues.append(IntegrityIssue(
            "expired_reservation", "Прострочені reservations", "Події", "medium", len(expired_reservations),
            "Резерв із waitlist уже прострочений, але lifecycle ще не оновив запис.",
            [f"Reg #{r.id}: event={r.event_id}, user={r.user_id}, до {r.reservation_expires_at}" for r in expired_reservations[:10]],
            "/admin/events", "refresh_event_operations"
        ))

    refs: list[tuple[str, int, str, str | None]] = []
    for u in users:
        refs.extend([("User", u.id, "badge_photo_path", u.badge_photo_path), ("User", u.id, "parental_consent_file_path", u.parental_consent_file_path)])
    for row in (await session.scalars(select(Event))).all(): refs.append(("Event", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(Quest))).all(): refs.append(("Quest", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(VolunteerTask))).all(): refs.append(("VolunteerTask", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(Opportunity))).all(): refs.append(("Opportunity", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(Reward))).all(): refs.append(("Reward", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(RequestCase))).all(): refs.append(("RequestCase", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(RequestMessage))).all(): refs.append(("RequestMessage", row.id, "image_path", row.image_path))
    for row in (await session.scalars(select(ActivityApplication))).all(): refs.append(("ActivityApplication", row.id, "result_image_path", row.result_image_path))
    missing_media = await _missing_media_samples(session, refs)
    if missing_media:
        issues.append(IntegrityIssue(
            "missing_media", "Missing media", "Файли", "medium", len(missing_media),
            "У БД є посилання на файл/MediaAsset, якого більше немає. Показано до 12 прикладів.",
            missing_media, "/admin/system-health"
        ))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues.sort(key=lambda item: (order.get(item.severity, 9), -item.count, item.title))
    totals = {
        "critical": sum(i.count for i in issues if i.severity == "critical"),
        "high": sum(i.count for i in issues if i.severity == "high"),
        "medium": sum(i.count for i in issues if i.severity == "medium"),
        "low": sum(i.count for i in issues if i.severity == "low"),
    }
    return {"issues": issues, "issue_groups": len(issues), "affected": sum(i.count for i in issues), "totals": totals, "duplicate_groups": duplicate_groups}
