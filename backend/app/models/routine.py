import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

# bit0 = Monday ... bit6 = Sunday. Default: Mon-Fri.
WEEKDAYS_DEFAULT = 0b0011111


class RoutineTemplate(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "routine_templates"
    __table_args__ = (CheckConstraint("weekdays BETWEEN 0 AND 127", name="weekdays_range"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    weekdays: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text(str(WEEKDAYS_DEFAULT))
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    blocks: Mapped[list["TimeBlock"]] = relationship(
        back_populates="template",
        order_by="TimeBlock.start_minute",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def runs_on(self, weekday: int) -> bool:
        """weekday follows date.weekday(): Monday == 0."""
        return bool(self.weekdays & (1 << weekday))


class TimeBlock(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "time_blocks"
    __table_args__ = (
        CheckConstraint("start_minute BETWEEN 0 AND 2879", name="start_minute_range"),
        CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="duration_range"),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("routine_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    # Minutes from local midnight of the log date; >= 1440 means the following day.
    start_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    template: Mapped[RoutineTemplate] = relationship(back_populates="blocks")

    @property
    def end_minute(self) -> int:
        return self.start_minute + self.duration_minutes
