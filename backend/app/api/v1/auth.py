from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import DB, CurrentUser
from app.schemas.auth import RefreshRequest, RegisterRequest, TokenPair, UserOut, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(prefix="/me", tags=["me"])


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: DB) -> TokenPair:
    user = await auth_service.register(db, data)
    tokens = await auth_service.issue_token_pair(db, user)
    await db.commit()
    return tokens


@router.post("/login", response_model=TokenPair)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB) -> TokenPair:
    user = await auth_service.authenticate(db, form.username, form.password)
    tokens = await auth_service.issue_token_pair(db, user)
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, db: DB) -> TokenPair:
    tokens = await auth_service.rotate_refresh_token(db, data.refresh_token)
    await db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, db: DB) -> Response:
    await auth_service.revoke_refresh_token(db, data.refresh_token)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@me_router.patch("", response_model=UserOut)
async def update_me(data: UserUpdate, user: CurrentUser, db: DB) -> UserOut:
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)
