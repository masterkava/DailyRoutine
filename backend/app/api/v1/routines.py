import uuid
from datetime import date

from fastapi import APIRouter, Query, Response, status

from app.core.deps import DB, CurrentUser
from app.models import RoutineTemplate
from app.schemas.routine import RoutineCreate, RoutineOut, RoutineUpdate, TimeBlockIn
from app.services import routine_service

router = APIRouter(prefix="/routines", tags=["routines"])


@router.get("", response_model=list[RoutineOut])
async def list_routines(user: CurrentUser, db: DB):
    return await routine_service.list_templates(db, user.id)


@router.post("", response_model=RoutineOut, status_code=status.HTTP_201_CREATED)
async def create_routine(data: RoutineCreate, user: CurrentUser, db: DB):
    template = RoutineTemplate(
        user_id=user.id, name=data.name, weekdays=data.weekdays, is_active=data.is_active, blocks=[]
    )
    db.add(template)
    await routine_service.replace_blocks(db, template, data.blocks)
    await db.commit()
    return template


@router.get("/for-date", response_model=RoutineOut | None)
async def routine_for_date(user: CurrentUser, db: DB, on: date = Query(alias="date")):
    """The active routine that applies on the given date, or null."""
    return await routine_service.template_for_date(db, user.id, on)


@router.get("/{routine_id}", response_model=RoutineOut)
async def get_routine(routine_id: uuid.UUID, user: CurrentUser, db: DB):
    return await routine_service.get_template(db, user.id, routine_id)


@router.patch("/{routine_id}", response_model=RoutineOut)
async def update_routine(routine_id: uuid.UUID, data: RoutineUpdate, user: CurrentUser, db: DB):
    template = await routine_service.get_template(db, user.id, routine_id)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    return template


@router.put("/{routine_id}/blocks", response_model=RoutineOut)
async def replace_routine_blocks(
    routine_id: uuid.UUID, blocks: list[TimeBlockIn], user: CurrentUser, db: DB
):
    """Replace every block of the routine. Overlapping blocks are rejected with 422."""
    template = await routine_service.get_template(db, user.id, routine_id)
    await routine_service.replace_blocks(db, template, blocks)
    await db.commit()
    return template


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(routine_id: uuid.UUID, user: CurrentUser, db: DB) -> Response:
    template = await routine_service.get_template(db, user.id, routine_id)
    await db.delete(template)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
