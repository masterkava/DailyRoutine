from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import auth, categories, logs, routines
from app.core.config import settings
from app.core.deps import DB
from app.core.errors import DomainError


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)

    @app.get("/healthz", tags=["health"])
    async def healthz(db: DB) -> dict[str, str]:
        await db.execute(text("SELECT 1"))
        return {"status": "ok"}

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    api.include_router(auth.me_router)
    api.include_router(categories.router)
    api.include_router(routines.router)
    api.include_router(logs.router)
    app.include_router(api)
    return app


app = create_app()
