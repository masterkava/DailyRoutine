"""Daily logs and their time entries.

Entries for a user never overlap (enforced by a deferred EXCLUDE constraint).
Writes follow "newest edit wins": an incoming entry carves its range out of
whatever was there before, deleting, trimming or splitting older entries in the
same transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, Unprocessable
from app.models import Category, DailyLog, EntrySource, LogEntry, User
from app.schemas.log import DailyLogUpdate, LogEntryCreate, LogEntryUpdate
from app.services import routine_service

MAX_ENTRY = timedelta(hours=24)
MAX_LIST_DAYS = 366


# --------------------------------------------------------------------------- logs


def log_window(user: User, log_date: date) -> tuple[datetime, datetime]:
    """Entries filed under log_date must fall inside [local midnight, +2 days).

    Matches the 0..2879 start_minute range of routine blocks, so a block that
    starts late and runs past midnight can still be logged on its own day.
    """
    start = routine_service.minute_to_utc(log_date, 0, user.timezone)
    end = routine_service.minute_to_utc(
        log_date, 2 * routine_service.MINUTES_PER_DAY, user.timezone
    )
    return start, end


async def _find_log(db: AsyncSession, user_id: uuid.UUID, log_date: date) -> DailyLog | None:
    return await db.scalar(
        select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
    )


async def get_or_create_log(db: AsyncSession, user: User, log_date: date) -> DailyLog:
    log = await _find_log(db, user.id, log_date)
    if log is not None:
        return log

    template = await routine_service.template_for_date(db, user.id, log_date)
    log = DailyLog(
        user_id=user.id,
        log_date=log_date,
        template_id=template.id if template else None,
        planned_snapshot=(
            routine_service.build_snapshot(template.blocks, log_date, user.timezone)
            if template
            else []
        ),
    )
    try:
        async with db.begin_nested():
            db.add(log)
    except IntegrityError:
        # A concurrent request created the same (user, date) first; use theirs.
        log = await _find_log(db, user.id, log_date)
        if log is None:  # pragma: no cover - would mean a different constraint failed
            raise
    return log


async def list_logs(
    db: AsyncSession, user_id: uuid.UUID, date_from: date, date_to: date
) -> Sequence[DailyLog]:
    if date_to < date_from:
        raise Unprocessable("'to' must not be before 'from'")
    if (date_to - date_from).days >= MAX_LIST_DAYS:
        raise Unprocessable(f"Range too large (max {MAX_LIST_DAYS} days)")
    return (
        await db.scalars(
            select(DailyLog)
            .where(
                DailyLog.user_id == user_id,
                DailyLog.log_date >= date_from,
                DailyLog.log_date <= date_to,
            )
            .order_by(DailyLog.log_date)
        )
    ).all()


async def update_log(
    db: AsyncSession, user: User, log_date: date, data: DailyLogUpdate
) -> DailyLog:
    log = await get_or_create_log(db, user, log_date)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    await db.flush()
    return log


async def entries_for_log(db: AsyncSession, log: DailyLog) -> Sequence[LogEntry]:
    return (
        await db.scalars(
            select(LogEntry).where(LogEntry.daily_log_id == log.id).order_by(LogEntry.started_at)
        )
    ).all()


# ------------------------------------------------------------------------ entries


async def _lock_user_entries(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialise entry writes per user for the rest of the transaction.

    Row locks can't stop a concurrent insert into the same time range, so take a
    transaction-scoped advisory lock keyed on the user instead.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(user_id)}
    )


async def _ensure_category(db: AsyncSession, user_id: uuid.UUID, category_id: uuid.UUID) -> None:
    owned = await db.scalar(
        select(exists().where(Category.id == category_id, Category.user_id == user_id))
    )
    if not owned:
        raise Unprocessable("Unknown category")


def _check_range(user: User, log_date: date, start: datetime, end: datetime) -> None:
    if end <= start:
        raise Unprocessable("ended_at must be after started_at")
    if end - start > MAX_ENTRY:
        raise Unprocessable("An entry can be at most 24 hours long")
    window_start, window_end = log_window(user, log_date)
    if start < window_start or end > window_end:
        raise Unprocessable(
            f"Entry must fall within {window_start.isoformat()} .. {window_end.isoformat()} "
            f"for log date {log_date.isoformat()}"
        )


async def _carve_out(
    db: AsyncSession,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Make room for [start, end) by editing every older entry that overlaps it."""
    query = select(LogEntry).where(
        LogEntry.user_id == user_id, LogEntry.started_at < end, LogEntry.ended_at > start
    )
    if exclude_id is not None:
        query = query.where(LogEntry.id != exclude_id)

    for old in (await db.scalars(query)).all():
        covers_left = start <= old.started_at
        covers_right = old.ended_at <= end
        if covers_left and covers_right:
            await db.delete(old)
        elif not covers_left and not covers_right:
            # New range sits strictly inside the old one: split it in two.
            db.add(
                LogEntry(
                    daily_log_id=old.daily_log_id,
                    user_id=old.user_id,
                    category_id=old.category_id,
                    planned_block_id=old.planned_block_id,
                    started_at=end,
                    ended_at=old.ended_at,
                    source=old.source,
                    note=old.note,
                )
            )
            old.ended_at = start
        elif not covers_left:
            old.ended_at = start  # old sticks out on the left: trim its right edge
        else:
            old.started_at = end  # old sticks out on the right: trim its left edge
    await db.flush()


async def _get_entry(
    db: AsyncSession, user_id: uuid.UUID, log_date: date, entry_id: uuid.UUID
) -> LogEntry:
    entry = await db.scalar(
        select(LogEntry)
        .join(DailyLog, DailyLog.id == LogEntry.daily_log_id)
        .where(
            LogEntry.id == entry_id,
            LogEntry.user_id == user_id,
            DailyLog.log_date == log_date,
        )
    )
    if entry is None:
        raise NotFound("Entry not found")
    return entry


async def create_entry(
    db: AsyncSession, user: User, log_date: date, data: LogEntryCreate
) -> tuple[LogEntry, bool]:
    """Returns (entry, created). Replaying a known client_id returns the stored entry."""
    await _lock_user_entries(db, user.id)

    if data.client_id is not None:
        existing = await db.scalar(select(LogEntry).where(LogEntry.client_id == data.client_id))
        if existing is not None:
            if existing.user_id != user.id:
                raise Conflict("client_id already in use")
            return existing, False

    start, end = data.started_at.astimezone(UTC), data.ended_at.astimezone(UTC)
    _check_range(user, log_date, start, end)
    await _ensure_category(db, user.id, data.category_id)
    log = await get_or_create_log(db, user, log_date)

    await _carve_out(db, user.id, start, end)
    entry = LogEntry(
        daily_log_id=log.id,
        user_id=user.id,
        category_id=data.category_id,
        planned_block_id=data.planned_block_id,
        started_at=start,
        ended_at=end,
        source=data.source,
        note=data.note,
        client_id=data.client_id,
    )
    db.add(entry)
    await db.flush()
    return entry, True


async def update_entry(
    db: AsyncSession, user: User, log_date: date, entry_id: uuid.UUID, data: LogEntryUpdate
) -> LogEntry:
    await _lock_user_entries(db, user.id)
    entry = await _get_entry(db, user.id, log_date, entry_id)
    changes = data.model_dump(exclude_unset=True)

    if changes.get("category_id") is not None:
        await _ensure_category(db, user.id, changes["category_id"])
    for field in ("category_id", "started_at", "ended_at"):
        if field in changes and changes[field] is None:
            raise Unprocessable(f"{field} cannot be null")

    start = changes.get("started_at", entry.started_at).astimezone(UTC)
    end = changes.get("ended_at", entry.ended_at).astimezone(UTC)
    times_changed = start != entry.started_at or end != entry.ended_at
    if times_changed:
        _check_range(user, log_date, start, end)
        await _carve_out(db, user.id, start, end, exclude_id=entry.id)

    category_changed = changes.get("category_id", entry.category_id) != entry.category_id
    entry.started_at, entry.ended_at = start, end
    entry.category_id = changes.get("category_id", entry.category_id)
    if "note" in changes:
        entry.note = changes["note"]
    if entry.source == EntrySource.planned and (times_changed or category_changed):
        entry.source = EntrySource.adjusted
    await db.flush()
    return entry


async def delete_entry(db: AsyncSession, user: User, log_date: date, entry_id: uuid.UUID) -> None:
    await _lock_user_entries(db, user.id)
    entry = await _get_entry(db, user.id, log_date, entry_id)
    await db.delete(entry)
    await db.flush()


async def accept_plan(db: AsyncSession, user: User, log_date: date) -> list[LogEntry]:
    """Turn each planned block into an entry, skipping blocks that already have
    any logged time overlapping them (real data always beats the plan)."""
    await _lock_user_entries(db, user.id)
    log = await get_or_create_log(db, user, log_date)

    category_ids = {uuid.UUID(b["category_id"]) for b in log.planned_snapshot}
    live_categories = set(
        await db.scalars(
            select(Category.id).where(Category.user_id == user.id, Category.id.in_(category_ids))
        )
    )

    created: list[LogEntry] = []
    for block in log.planned_snapshot:
        category_id = uuid.UUID(block["category_id"])
        if category_id not in live_categories:
            continue
        start = datetime.fromisoformat(block["start"])
        end = datetime.fromisoformat(block["end"])
        overlapping = await db.scalar(
            select(func.count())
            .select_from(LogEntry)
            .where(
                LogEntry.user_id == user.id, LogEntry.started_at < end, LogEntry.ended_at > start
            )
        )
        if overlapping:
            continue
        entry = LogEntry(
            daily_log_id=log.id,
            user_id=user.id,
            category_id=category_id,
            planned_block_id=uuid.UUID(block["block_id"]),
            started_at=start,
            ended_at=end,
            source=EntrySource.planned,
        )
        db.add(entry)
        await db.flush()
        created.append(entry)
    return created
