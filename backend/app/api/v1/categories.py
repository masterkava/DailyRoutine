import uuid

from fastapi import APIRouter, status
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import DB, CurrentUser
from app.core.errors import Conflict, NotFound
from app.models import Category, LogEntry, TimeBlock
from app.schemas.category import (
    CategoryCreate,
    CategoryDeleteResult,
    CategoryOut,
    CategoryUpdate,
)

router = APIRouter(prefix="/categories", tags=["categories"])


async def _get_owned(db: DB, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    category = await db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise NotFound("Category not found")
    return category


@router.get("", response_model=list[CategoryOut])
async def list_categories(user: CurrentUser, db: DB, include_archived: bool = False):
    query = select(Category).where(Category.user_id == user.id).order_by(Category.created_at)
    if not include_archived:
        query = query.where(Category.is_archived.is_(False))
    return (await db.scalars(query)).all()


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(data: CategoryCreate, user: CurrentUser, db: DB):
    category = Category(user_id=user.id, **data.model_dump())
    db.add(category)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A category with that name already exists") from exc
    return category


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: uuid.UUID, user: CurrentUser, db: DB):
    return await _get_owned(db, user.id, category_id)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: uuid.UUID, data: CategoryUpdate, user: CurrentUser, db: DB):
    category = await _get_owned(db, user.id, category_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None and field != "icon":
            continue
        setattr(category, field, value)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A category with that name already exists") from exc
    await db.refresh(category)
    return category


@router.delete("/{category_id}", response_model=CategoryDeleteResult)
async def delete_category(category_id: uuid.UUID, user: CurrentUser, db: DB):
    """Hard-deletes an unused category; archives it if blocks or entries still use it."""
    category = await _get_owned(db, user.id, category_id)
    in_use = await db.scalar(
        select(
            or_(
                exists().where(TimeBlock.category_id == category.id),
                exists().where(LogEntry.category_id == category.id),
            )
        )
    )
    if in_use:
        category.is_archived = True
        await db.commit()
        return CategoryDeleteResult(id=category_id, deleted=False, archived=True)
    await db.delete(category)
    await db.commit()
    return CategoryDeleteResult(id=category_id, deleted=True, archived=False)
