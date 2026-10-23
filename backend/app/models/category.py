import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import CategoryKind, pg_enum


class Category(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_categories_user_id_name"),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color_hex"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[CategoryKind] = mapped_column(
        pg_enum(CategoryKind, "category_kind"), nullable=False
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
