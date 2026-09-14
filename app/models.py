from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    PARTICIPANT = "participant"
    AMBASSADOR = "ambassador"
    COORDINATOR = "coordinator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"
    DELETED = "deleted"
    DELETED_PERMANENT = "deleted_permanent"


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(64), default="other", index=True)
    filename: Mapped[str] = mapped_column(String(255), default="image.webp")
    content_type: Mapped[str] = mapped_column(String(80), default="image/webp")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SettlementReference(Base):
    __tablename__ = "settlement_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    profile_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    restarted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User | None] = relationship(foreign_keys=[user_id])


class BanRecord(Base):
    __tablename__ = "ban_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    issued_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="web")
    reason: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    original_ends_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lift_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    issued_by: Mapped[User | None] = relationship(foreign_keys=[issued_by_user_id])


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    starts_at: Mapped[date] = mapped_column(Date)
    ends_at: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    history_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class XPTransaction(Base):
    __tablename__ = "xp_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(64), default="other")
    description: Mapped[str] = mapped_column(String(255))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(foreign_keys=[user_id], back_populates="xp_transactions")
    season: Mapped[Season | None] = relationship()


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(180), default="АМП")
    xp_reward: Mapped[int] = mapped_column(Integer, default=10)
    volunteer_hours: Mapped[float] = mapped_column(Float, default=0)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    checkin_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    registration_template_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    registration_template_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_template_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    postponed_reason: Mapped[str] = mapped_column(Text, default="")
    postponed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    registrations: Mapped[list["EventRegistration"]] = relationship(back_populates="event")


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="registered")
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    checkin_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attendance_signature: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attendance_signature_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attendance_signature_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attendance_confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reminder_1h_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    waitlisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    waitlist_promoted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    no_show_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship(back_populates="registrations")
    user: Mapped[User] = relationship(back_populates="registrations", foreign_keys=[user_id])


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(140), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    xp_reward: Mapped[int] = mapped_column(Integer, default=20)
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    quest_type: Mapped[str] = mapped_column(String(24), default="individual")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    target_value: Mapped[int] = mapped_column(Integer, default=1)
    progress_value: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    postponed_reason: Mapped[str] = mapped_column(Text, default="")
    postponed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    participations: Mapped[list["QuestParticipation"]] = relationship(back_populates="quest")
    team: Mapped[Team | None] = relationship()


class QuestParticipation(Base):
    __tablename__ = "quest_participations"
    __table_args__ = (UniqueConstraint("quest_id", "user_id", name="uq_quest_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="joined")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    quest: Mapped[Quest] = relationship(back_populates="participations")
    user: Mapped[User] = relationship(back_populates="quest_participations")


class TeamQuestContribution(Base):
    __tablename__ = "team_quest_contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    value: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(255), default="")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    icon: Mapped[str] = mapped_column(String(16), default="🏅")
    description: Mapped[str] = mapped_column(Text, default="")
    criteria_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    criteria_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    badge_type: Mapped[str] = mapped_column(String(24), default="general", index=True)


class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"), index=True)
    awarded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="badges", foreign_keys=[user_id])
    badge: Mapped[Badge] = relationship()


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("invited_user_id", name="uq_referral_invited_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inviter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    invited_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[str] = mapped_column(Text, default="")
    clawback_xp: Mapped[int] = mapped_column(Integer, default=0)


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    min_xp: Mapped[int] = mapped_column(Integer, default=0)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    reward_type: Mapped[str] = mapped_column(String(32), default="item", index=True)  # item|service|streak_restore


class RewardClaim(Base):
    __tablename__ = "reward_claims"
    __table_args__ = (UniqueConstraint("reward_id", "user_id", name="uq_reward_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reward_id: Mapped[int] = mapped_column(ForeignKey("rewards.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="requested")
    xp_spent: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ParticipationStreak(Base):
    __tablename__ = "participation_streaks"
    __table_args__ = (UniqueConstraint("user_id", name="uq_participation_streak_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    weekly_streak: Mapped[int] = mapped_column(Integer, default=0)
    weekly_best: Mapped[int] = mapped_column(Integer, default=0)
    weekly_last_key: Mapped[str | None] = mapped_column(String(12), nullable=True)
    event_streak: Mapped[int] = mapped_column(Integer, default=0)
    event_best: Mapped[int] = mapped_column(Integer, default=0)
    event_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    event_consecutive_misses: Mapped[int] = mapped_column(Integer, default=0)
    event_total_misses: Mapped[int] = mapped_column(Integer, default=0)
    event_last_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recoverable_event_streak: Mapped[int] = mapped_column(Integer, default=0)
    recoverable_event_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recoverable_saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    restores_used: Mapped[int] = mapped_column(Integer, default=0)
    manual_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship()


class StreakFreeze(Base):
    __tablename__ = "streak_freezes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    days: Mapped[int] = mapped_column(Integer, default=1)
    quarter_key: Mapped[str] = mapped_column(String(8), index=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="web")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship()


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(48), default="other")
    problem: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    expected_result: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    project_team: Mapped[str] = mapped_column(Text, default="")
    implementation_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    budget_resources: Mapped[str] = mapped_column(Text, default="")
    project_tasks: Mapped[str] = mapped_column(Text, default="")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    implementation_result: Mapped[str] = mapped_column(Text, default="")
    result_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    implementation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approval_xp_awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RequestCase(Base):
    __tablename__ = "request_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40), default="problem", index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(24), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    response_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_response: Mapped[str] = mapped_column(Text, default="")
    internal_note: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    participant_last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RequestMessage(Base):
    __tablename__ = "request_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("request_cases.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(24), default="participant", index=True)
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    case: Mapped[RequestCase] = relationship()
    sender: Mapped[User | None] = relationship()


class VolunteerTask(Base):
    __tablename__ = "volunteer_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=20)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    max_participants: Mapped[int] = mapped_column(Integer, default=1)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    postponed_reason: Mapped[str] = mapped_column(Text, default="")
    postponed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Legacy single-assignee field is kept for backward compatibility only.
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    participations: Mapped[list["VolunteerTaskParticipation"]] = relationship(back_populates="task")


class VolunteerTaskParticipation(Base):
    __tablename__ = "volunteer_task_participations"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_volunteer_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("volunteer_tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="joined", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")

    task: Mapped[VolunteerTask] = relationship(back_populates="participations")
    user: Mapped[User] = relationship()


class ActivityType(Base):
    __tablename__ = "activity_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(64), default="other", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=10)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActivityApplication(Base):
    __tablename__ = "activity_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_type_id: Mapped[int] = mapped_column(ForeignKey("activity_types.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="activity_requested", index=True)
    plan_text: Mapped[str] = mapped_column(Text, default="")
    result_note: Mapped[str] = mapped_column(Text, default="")
    result_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    activity_type: Mapped[ActivityType] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(80), default="можливість")
    direction: Mapped[str] = mapped_column(String(100), default="Інше")
    format: Mapped[str] = mapped_column(String(80), default="Онлайн/офлайн")
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    target_settlements: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OpportunityMatch(Base):
    __tablename__ = "opportunity_matches"
    __table_args__ = (UniqueConstraint("opportunity_id", "user_id", name="uq_opportunity_match_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    reasons_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="matched", index=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity: Mapped[Opportunity] = relationship()
    user: Mapped[User] = relationship()


class OpportunityInterest(Base):
    __tablename__ = "opportunity_interests"
    __table_args__ = (UniqueConstraint("opportunity_id", "user_id", name="uq_opportunity_interest_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="interested", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    opportunity: Mapped[Opportunity] = relationship()
    user: Mapped[User] = relationship()


class DonationJarState(Base):
    __tablename__ = "donation_jar_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    jar_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    send_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(180), nullable=True)
    balance_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    goal_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DonationTransaction(Base):
    __tablename__ = "donation_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_transaction_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    amount_kop: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    currency_code: Mapped[int] = mapped_column(Integer, default=980)
    description: Mapped[str] = mapped_column(Text, default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    counter_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    receipt_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    linked_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    linked_user: Mapped[User | None] = relationship(foreign_keys=[linked_user_id])


class DonationReport(Base):
    __tablename__ = "donation_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str] = mapped_column(Text, default="")
    amount_spent_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    spent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    document_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportPageView(Base):
    __tablename__ = "support_page_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(24), default="season", index=True)  # season|personal|team
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    task_text: Mapped[str] = mapped_column(Text, default="")
    metric: Mapped[str] = mapped_column(String(40), default="xp")  # xp|visits|hours|quests|activities|ideas
    target_value: Mapped[float] = mapped_column(Float, default=1)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), nullable=True, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reward_xp: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User | None] = relationship()
    season: Mapped[Season | None] = relationship()


class GoalReward(Base):
    __tablename__ = "goal_rewards"
    __table_args__ = (UniqueConstraint("goal_id", "user_id", name="uq_goal_reward_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    goal: Mapped[Goal] = relationship()
    user: Mapped[User] = relationship()


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
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship()


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)  # draft|published|closed
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(24), default="single")  # single|multiple|text
    options_text: Mapped[str] = mapped_column(Text, default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    survey: Mapped[Survey] = relationship()


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (UniqueConstraint("survey_id", "user_id", name="uq_survey_response_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    survey: Mapped[Survey] = relationship()
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()


class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="superadmin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(24), default="web")
    author_label: Mapped[str] = mapped_column(String(160), default="superadmin")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    audience_type: Mapped[str] = mapped_column(String(40), default="all", index=True)
    audience_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inactive_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    recipients: Mapped[list["BroadcastRecipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_broadcast_campaign_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("broadcast_campaigns.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(160), default="")
    recipient_tg_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error_text: Mapped[str] = mapped_column(String(500), default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    campaign: Mapped[BroadcastCampaign] = relationship(back_populates="recipients")
    user: Mapped[User] = relationship()


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    job_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    locked_by: Mapped[str | None] = mapped_column(String(180), nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(220), unique=True, index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="system", index=True)
    recipient_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_text: Mapped[str] = mapped_column(Text)
    parse_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    callback_data: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)  # pending|retry|sent|failed
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Notification(Base):
    """Canonical v1.9 notification/outbox record.

    All participant-facing Telegram messages are queued here. Legacy
    notification_deliveries stays in the schema for backward compatibility,
    but new producers use this table through queue_telegram_delivery().
    """
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(220), unique=True, index=True, nullable=True)
    recipient_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    recipient_tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    type: Mapped[str] = mapped_column(String(48), default="system", index=True)
    title: Mapped[str] = mapped_column(String(180), default="")
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)  # queued|retry|sent|failed
    error: Mapped[str] = mapped_column(String(500), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parse_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    callback_data: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    recipient: Mapped[User | None] = relationship(foreign_keys=[recipient_user_id])


class EventFeedback(Base):
    """Post-event outcome feedback used by donor/council reporting."""
    __tablename__ = "event_feedback"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_feedback_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    useful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    new_knowledge: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    felt_safe: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    would_return: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)  # pending|in_progress|completed
    prompted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    event: Mapped[Event] = relationship()
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sessions: Mapped[list["WebAdminSession"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class WebAdminSession(Base):
    __tablename__ = "web_admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("web_staff_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), default="")
    ip_address: Mapped[str] = mapped_column(String(96), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
