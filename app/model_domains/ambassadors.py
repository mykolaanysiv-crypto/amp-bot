from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base


class AmbassadorReport(Base):
    __tablename__ = "ambassador_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)

    user = relationship("User")


class TeamTask(Base):
    """Personal task assigned to an AMP team member.

    A task always requires a written completion report. XP is awarded only once,
    when a submitted report is approved. The persisted ``xp_awarded_at`` marker
    makes the award idempotent across repeated web requests.
    """

    __tablename__ = "team_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignee_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=10)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="assigned", index=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    report_text: Mapped[str] = mapped_column(Text, default="")
    report_photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    xp_awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignee = relationship("User", foreign_keys=[assignee_user_id])
