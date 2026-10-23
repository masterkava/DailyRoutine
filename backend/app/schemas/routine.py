import uuid

from pydantic import Field

from app.models.routine import WEEKDAYS_DEFAULT
from app.schemas.common import BaseModel


class TimeBlockIn(BaseModel):
    category_id: uuid.UUID
    title: str = Field(min_length=1, max_length=100)
    start_minute: int = Field(
        ge=0, le=2879, description="Minutes from local midnight; >=1440 is next day"
    )
    duration_minutes: int = Field(ge=1, le=1440)
    notes: str | None = None


class TimeBlockOut(TimeBlockIn):
    id: uuid.UUID


class RoutineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weekdays: int = Field(
        default=WEEKDAYS_DEFAULT, ge=0, le=127, description="bit0=Mon .. bit6=Sun"
    )
    is_active: bool = True
    blocks: list[TimeBlockIn] = Field(default_factory=list)


class RoutineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    weekdays: int | None = Field(default=None, ge=0, le=127)
    is_active: bool | None = None


class RoutineOut(BaseModel):
    id: uuid.UUID
    name: str
    weekdays: int
    is_active: bool
    blocks: list[TimeBlockOut]
