from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

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
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class SupportPageView(Base):
    __tablename__ = "support_page_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
