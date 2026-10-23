import uuid

from pydantic import Field

from app.models.enums import CategoryKind
from app.schemas.common import BaseModel

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(pattern=HEX_COLOR)
    icon: str | None = Field(default=None, max_length=40)
    kind: CategoryKind


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, pattern=HEX_COLOR)
    icon: str | None = Field(default=None, max_length=40)
    kind: CategoryKind | None = None
    is_archived: bool | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    icon: str | None
    kind: CategoryKind
    is_archived: bool


class CategoryDeleteResult(BaseModel):
    id: uuid.UUID
    deleted: bool
    archived: bool
