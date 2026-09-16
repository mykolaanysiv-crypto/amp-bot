from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(64), default="other", index=True)
    filename: Mapped[str] = mapped_column(String(255), default="image.webp")
    content_type: Mapped[str] = mapped_column(String(80), default="image/webp")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class SettlementReference(Base):
    __tablename__ = "settlement_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(160))
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settlement: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(24), nullable=True)
    vulnerability_categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_consent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    media_consent_status: Mapped[str] = mapped_column(String(24), default="pending")
    media_consent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    media_consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    privacy_notice_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    birthday_reward_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.PARTICIPANT.value)
    status: Mapped[str] = mapped_column(String(24), default=UserStatus.PENDING.value)
    parental_consent_required: Mapped[bool] = mapped_column(Boolean, default=False)
    parental_consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    parental_consent_status: Mapped[str] = mapped_column(String(24), default="not_required")
    parental_consent_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parental_consent_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    leaderboard_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    volunteer_hours: Mapped[float] = mapped_column(Float, default=0)
    wallet_xp: Mapped[int] = mapped_column(Integer, default=0)
    public_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    badge_photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    deletion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    restoration_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    restoration_request_status: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    restoration_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    restoration_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    restoration_reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    probation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    probation_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    permanent_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opportunity_interests_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    staff_permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_review_status: Mapped[str] = mapped_column(String(24), default="approved", index=True)
    registration_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    registration_reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    registration_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    xp_transactions: Mapped[list["XPTransaction"]] = relationship(back_populates="user", foreign_keys="XPTransaction.user_id")
    registrations: Mapped[list["EventRegistration"]] = relationship(back_populates="user", foreign_keys="EventRegistration.user_id")
    quest_participations: Mapped[list["QuestParticipation"]] = relationship(back_populates="user")
    badges: Mapped[list["UserBadge"]] = relationship(back_populates="user", foreign_keys="UserBadge.user_id")

class RegistrationJourney(Base):
    """Persistent registration checkpoint + privacy-preserving funnel metrics.

    The questionnaire draft is encrypted by the application before it is stored
    in ``draft_ciphertext``. Funnel timestamps contain no answers and are safe to
    aggregate for conversion reporting.
    """
    __tablename__ = "registration_journeys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    current_step: Mapped[str] = mapped_column(String(48), default="privacy_notice", index=True)
    draft_ciphertext: Mapped[str] = mapped_column(Text, default="")
    start_payload: Mapped[str] = mapped_column(String(180), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    profile_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    restarted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])

class BanRecord(Base):
    __tablename__ = "ban_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="web")
    reason: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    original_ends_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lift_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    issued_by: Mapped[User | None] = relationship(foreign_keys=[issued_by_user_id])

class ConsentHistory(Base):
    __tablename__ = "consent_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(24), index=True)  # parental|media
    status: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    changed_by_label: Mapped[str] = mapped_column(String(160), default="system")
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)

    user: Mapped[User] = relationship()

class UserStatusChangeRequest(Base):
    __tablename__ = "user_status_change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    previous_status: Mapped[str] = mapped_column(String(24))
    requested_status: Mapped[str] = mapped_column(String(24))
    requested_by_label: Mapped[str] = mapped_column(String(160), default="web")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)  # pending|approved|rejected
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()

class WebStaffAccount(Base):
    __tablename__ = "web_staff_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32), default="admin", index=True)
    permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    sessions: Mapped[list["WebAdminSession"]] = relationship(back_populates="account", cascade="all, delete-orphan")

class WebAdminSession(Base):
    __tablename__ = "web_admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("web_staff_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), default="")
    ip_address: Mapped[str] = mapped_column(String(96), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    account: Mapped[WebStaffAccount] = relationship(back_populates="sessions")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_label: Mapped[str] = mapped_column(String(160), default="system")
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
