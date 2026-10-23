import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, Field, model_validator

from app.models.enums import EntrySource, LogStatus
from app.schemas.common import BaseModel


class PlannedBlock(BaseModel):
    block_id: uuid.UUID
    category_id: uuid.UUID
    title: str
    start: datetime
    end: datetime


class LogEntryCreate(BaseModel):
    category_id: uuid.UUID
    started_at: AwareDatetime
    ended_at: AwareDatetime
    source: EntrySource = EntrySource.manual
    note: str | None = None
    planned_block_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = Field(
        default=None, description="Client-generated id; replays with the same id are no-ops"
    )

    @model_validator(mode="after")
    def _check_range(self) -> "LogEntryCreate":
        if self.ended_at <= self.started_at:
            raise ValueError("ended_at must be after started_at")
        return self


class LogEntryUpdate(BaseModel):
    category_id: uuid.UUID | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    note: str | None = None


class LogEntryOut(BaseModel):
    id: uuid.UUID
    daily_log_id: uuid.UUID
    category_id: uuid.UUID
    planned_block_id: uuid.UUID | None
    started_at: datetime
    ended_at: datetime
    source: EntrySource
    note: str | None
    client_id: uuid.UUID | None


class DailyLogUpdate(BaseModel):
    status: LogStatus | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    reflection: str | None = None


class DailyLogSummaryOut(BaseModel):
    id: uuid.UUID
    log_date: date
    template_id: uuid.UUID | None
    status: LogStatus
    mood: int | None
    energy: int | None
    reflection: str | None
    planned_snapshot: list[PlannedBlock]


class DailyLogOut(DailyLogSummaryOut):
    entries: list[LogEntryOut]
