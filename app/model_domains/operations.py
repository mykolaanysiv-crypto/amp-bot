from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..time_utils import utc_storage_now
from .base import Base

class OperationalIssue(Base):
    __tablename__ = "operational_issues"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_operational_issue_fingerprint"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(220), index=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    title: Mapped[str] = mapped_column(String(220))
    details: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action_url: Mapped[str] = mapped_column(String(500), default="/admin/dashboard")
    assignee_label: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)  # open|resolved
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
