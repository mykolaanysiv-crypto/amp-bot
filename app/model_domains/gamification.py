from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    starts_at: Mapped[date] = mapped_column(Date)
    ends_at: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    user: Mapped[User] = relationship(foreign_keys=[user_id], back_populates="xp_transactions")
    season: Mapped[Season | None] = relationship()

class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(140), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    seed_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)

class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (UniqueConstraint("user_id", "badge_id", name="uq_user_badge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"), index=True)
    awarded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
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
    reward_type: Mapped[str] = mapped_column(String(32), default="item", index=True)

class RewardClaim(Base):
    __tablename__ = "reward_claims"
    __table_args__ = (UniqueConstraint("reward_id", "user_id", name="uq_reward_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reward_id: Mapped[int] = mapped_column(ForeignKey("rewards.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="requested")
    xp_spent: Mapped[int] = mapped_column(Integer, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)

    user: Mapped[User] = relationship()

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
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reward_xp: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    user: Mapped[User | None] = relationship()
    season: Mapped[Season | None] = relationship()

class GoalReward(Base):
    __tablename__ = "goal_rewards"
    __table_args__ = (UniqueConstraint("goal_id", "user_id", name="uq_goal_reward_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    goal: Mapped[Goal] = relationship()
    user: Mapped[User] = relationship()
