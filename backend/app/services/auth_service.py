from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import Category, CategoryKind, RefreshToken, User
from app.schemas.auth import RegisterRequest, TokenPair

DEFAULT_CATEGORIES: list[tuple[str, str, str, CategoryKind]] = [
    ("Sleep", "#6366F1", "bed", CategoryKind.maintenance),
    ("Office", "#0EA5E9", "briefcase", CategoryKind.productive),
    ("Side Geek", "#8B5CF6", "code", CategoryKind.productive),
    ("Family", "#F59E0B", "home", CategoryKind.leisure),
    ("Fitness", "#10B981", "dumbbell", CategoryKind.productive),
    ("Commute", "#64748B", "car", CategoryKind.maintenance),
    ("Meals", "#F97316", "utensils", CategoryKind.maintenance),
    ("Leisure", "#EC4899", "gamepad", CategoryKind.leisure),
]

# Verified against when the email is unknown so login timing doesn't leak which emails exist.
_DUMMY_HASH = hash_password("not-a-real-password")


def _now() -> datetime:
    return datetime.now(UTC)


async def register(db: AsyncSession, data: RegisterRequest) -> User:
    email = data.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("Email already registered")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
        timezone=data.timezone,
    )
    db.add(user)
    await db.flush()
    db.add_all(
        Category(user_id=user.id, name=name, color=color, icon=icon, kind=kind)
        for name, color, icon, kind in DEFAULT_CATEGORIES
    )
    await db.flush()
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("Incorrect email or password")
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise Unauthorized("Incorrect email or password")
    return user


async def issue_token_pair(db: AsyncSession, user: User) -> TokenPair:
    raw = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw),
            expires_at=_now() + timedelta(days=settings.refresh_token_days),
        )
    )
    await db.flush()
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=settings.access_token_minutes * 60,
    )


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> TokenPair:
    """Exchange a refresh token for a new pair, revoking the old one.

    Presenting an already-revoked token is treated as theft: every live refresh
    token for that user is revoked, forcing a fresh login everywhere.
    """
    now = _now()
    row = await db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    if row is None:
        raise Unauthorized("Invalid refresh token")
    if row.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        raise Unauthorized("Refresh token has been revoked")
    if row.expires_at <= now:
        raise Unauthorized("Refresh token expired")

    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Invalid refresh token")

    row.revoked_at = now
    return await issue_token_pair(db, user)


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(raw_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
