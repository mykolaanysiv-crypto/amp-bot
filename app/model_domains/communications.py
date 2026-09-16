from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="superadmin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)  # queued|retry|sent|failed
    error: Mapped[str] = mapped_column(String(500), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parse_mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    button_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    callback_data: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    recipient: Mapped[User | None] = relationship(foreign_keys=[recipient_user_id])
