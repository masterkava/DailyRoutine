import uuid
from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.core.deps import DB, CurrentUser
from app.models import DailyLog
from app.schemas.log import (
    DailyLogOut,
    DailyLogSummaryOut,
    DailyLogUpdate,
    LogEntryCreate,
    LogEntryOut,
    LogEntryUpdate,
)
from app.services import log_service

router = APIRouter(prefix="/logs", tags=["logs"])


async def _log_out(db: DB, log: DailyLog) -> DailyLogOut:
    entries = await log_service.entries_for_log(db, log)
    return DailyLogOut.model_validate(
        {**DailyLogSummaryOut.model_validate(log).model_dump(), "entries": entries}
    )


@router.get("", response_model=list[DailyLogSummaryOut])
async def list_logs(
    user: CurrentUser,
    db: DB,
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
):
    """Existing logs in [from, to]. Does not create missing days."""
    return await log_service.list_logs(db, user.id, date_from, date_to)


@router.get("/{log_date}", response_model=DailyLogOut)
async def get_log(log_date: date, user: CurrentUser, db: DB):
    """Fetch the day's log, creating it (with a snapshot of the matching routine) if needed."""
    log = await log_service.get_or_create_log(db, user, log_date)
    await db.commit()
    return await _log_out(db, log)


@router.patch("/{log_date}", response_model=DailyLogOut)
async def update_log(log_date: date, data: DailyLogUpdate, user: CurrentUser, db: DB):
    log = await log_service.update_log(db, user, log_date, data)
    await db.commit()
    return await _log_out(db, log)


@router.post("/{log_date}/entries", response_model=LogEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    log_date: date, data: LogEntryCreate, user: CurrentUser, db: DB, response: Response
):
    """Add an entry. Overlapping older entries are trimmed, split or removed.

    Sending the same client_id again returns the stored entry with 200.
    """
    entry, created = await log_service.create_entry(db, user, log_date, data)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return entry


@router.patch("/{log_date}/entries/{entry_id}", response_model=LogEntryOut)
async def update_entry(
    log_date: date, entry_id: uuid.UUID, data: LogEntryUpdate, user: CurrentUser, db: DB
):
    entry = await log_service.update_entry(db, user, log_date, entry_id, data)
    await db.commit()
    return entry


@router.delete("/{log_date}/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(log_date: date, entry_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    await log_service.delete_entry(db, user, log_date, entry_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{log_date}/accept-plan", response_model=DailyLogOut)
async def accept_plan(log_date: date, user: CurrentUser, db: DB):
    """Fill the day from the plan wherever nothing has been logged yet."""
    await log_service.accept_plan(db, user, log_date)
    log = await log_service.get_or_create_log(db, user, log_date)
    await db.commit()
    return await _log_out(db, log)
