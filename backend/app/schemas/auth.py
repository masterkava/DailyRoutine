import uuid

from pydantic import EmailStr, Field

from app.schemas.common import BaseModel, TimezoneName


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: TimezoneName = "UTC"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    timezone: str
    day_start_minute: int
    is_active: bool


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: TimezoneName | None = None
    day_start_minute: int | None = Field(default=None, ge=0, le=1439)
