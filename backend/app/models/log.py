import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import EntrySource, LogStatus, pg_enum


class DailyLog(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_daily_logs_user_id_log_date"),
        CheckConstraint("mood IS NULL OR mood BETWEEN 1 AND 5", name="mood_range"),
        CheckConstraint("energy IS NULL OR energy BETWEEN 1 AND 5", name="energy_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("routine_templates.id", ondelete="SET NULL")
    )
    # [{block_id, category_id, title, start, end}] with ISO-8601 UTC timestamps.
    planned_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[LogStatus] = mapped_column(
        pg_enum(LogStatus, "log_status"), nullable=False, server_default=LogStatus.open.value
    )
    mood: Mapped[int | None] = mapped_column(SmallInteger)
    energy: Mapped[int | None] = mapped_column(SmallInteger)
    reflection: Mapped[str | None] = mapped_column(Text)

    entries: Mapped[list["LogEntry"]] = relationship(
        back_populates="daily_log",
        order_by="LogEntry.started_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class LogEntry(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "log_entries"
    # The no-overlap EXCLUDE constraint lives in the migration (needs btree_gist).
    __table_args__ = (
        CheckConstraint("ended_at > started_at", name="ended_after_started"),
        Index("ix_log_entries_user_id_started_at", "user_id", "started_at"),
    )

    daily_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    planned_block_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[EntrySource] = mapped_column(
        pg_enum(EntrySource, "entry_source"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)

    daily_log: Mapped[DailyLog] = relationship(back_populates="entries")


class DailySummary(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "log_date", "category_id", name="uq_daily_summaries_user_date_category"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    actual_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    aligned_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
