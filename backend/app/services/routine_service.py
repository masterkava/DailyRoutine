import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, Unprocessable
from app.models import Category, RoutineTemplate, TimeBlock
from app.schemas.routine import TimeBlockIn

MINUTES_PER_DAY = 1440


def minute_to_utc(log_date: date, minute: int, tz_name: str) -> datetime:
    """Turn "minutes from local midnight of log_date" into an aware UTC datetime.

    Minutes >= 1440 roll over into following days. Uses wall-clock time in the
    user's zone, so a 07:00 block stays at 07:00 local across DST changes.
    """
    day_offset, minute_of_day = divmod(minute, MINUTES_PER_DAY)
    local = datetime.combine(
        log_date + timedelta(days=day_offset),
        time(minute_of_day // 60, minute_of_day % 60),
        tzinfo=ZoneInfo(tz_name),
    )
    return local.astimezone(UTC)


def build_snapshot(
    blocks: Iterable[TimeBlock], log_date: date, tz_name: str
) -> list[dict[str, Any]]:
    snapshot = []
    for block in sorted(blocks, key=lambda b: b.start_minute):
        start = minute_to_utc(log_date, block.start_minute, tz_name)
        end = start + timedelta(minutes=block.duration_minutes)
        snapshot.append(
            {
                "block_id": str(block.id),
                "category_id": str(block.category_id),
                "title": block.title,
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
    return snapshot


def validate_blocks(blocks: Sequence[TimeBlockIn]) -> None:
    """Reject blocks that overlap each other within one template."""
    ordered = sorted(blocks, key=lambda b: b.start_minute)
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        if prev.start_minute + prev.duration_minutes > nxt.start_minute:
            raise Unprocessable(
                f"Blocks overlap: {prev.title!r} ({prev.start_minute}+{prev.duration_minutes}m) "
                f"and {nxt.title!r} (starts {nxt.start_minute})"
            )


async def ensure_categories_owned(
    db: AsyncSession, user_id: uuid.UUID, category_ids: Iterable[uuid.UUID]
) -> None:
    wanted = set(category_ids)
    if not wanted:
        return
    found = set(
        await db.scalars(
            select(Category.id).where(Category.user_id == user_id, Category.id.in_(wanted))
        )
    )
    missing = wanted - found
    if missing:
        raise Unprocessable(f"Unknown category id(s): {', '.join(sorted(map(str, missing)))}")


async def get_template(
    db: AsyncSession, user_id: uuid.UUID, template_id: uuid.UUID
) -> RoutineTemplate:
    template = await db.scalar(
        select(RoutineTemplate).where(
            RoutineTemplate.id == template_id, RoutineTemplate.user_id == user_id
        )
    )
    if template is None:
        raise NotFound("Routine not found")
    return template


async def list_templates(db: AsyncSession, user_id: uuid.UUID) -> Sequence[RoutineTemplate]:
    return (
        await db.scalars(
            select(RoutineTemplate)
            .where(RoutineTemplate.user_id == user_id)
            .order_by(RoutineTemplate.created_at)
        )
    ).all()


async def template_for_date(
    db: AsyncSession, user_id: uuid.UUID, log_date: date
) -> RoutineTemplate | None:
    """The active template that runs on log_date's weekday (most recently edited wins)."""
    bit = 1 << log_date.weekday()
    return await db.scalar(
        select(RoutineTemplate)
        .where(
            RoutineTemplate.user_id == user_id,
            RoutineTemplate.is_active.is_(True),
            RoutineTemplate.weekdays.op("&")(bit) != 0,
        )
        .order_by(RoutineTemplate.updated_at.desc(), RoutineTemplate.created_at.desc())
        .limit(1)
    )


async def replace_blocks(
    db: AsyncSession, template: RoutineTemplate, blocks: Sequence[TimeBlockIn]
) -> RoutineTemplate:
    validate_blocks(blocks)
    await ensure_categories_owned(db, template.user_id, (b.category_id for b in blocks))
    template.blocks = [TimeBlock(**b.model_dump()) for b in blocks]
    await db.flush()
    await db.refresh(template, ["blocks"])
    return template
