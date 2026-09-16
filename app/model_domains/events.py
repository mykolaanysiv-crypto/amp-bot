from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    registrations: Mapped[list["EventRegistration"]] = relationship(back_populates="event")

class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="registered")
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    event: Mapped[Event] = relationship()
    user: Mapped[User] = relationship()
