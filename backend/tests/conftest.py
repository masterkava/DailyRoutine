"""Test fixtures. Tests run against a real Postgres (TEST_DATABASE_URL).

The schema is rebuilt once per session by running the Alembic migrations, so the
migration itself (btree_gist, EXCLUDE constraint, ...) is exercised too. Tables are
truncated before every test.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import NullPool, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.core.config import settings
from app.db.session import get_db
from app.main import app

TEST_DB_URL = settings.test_database_url
BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = (
    "log_entries, daily_summaries, daily_logs, time_blocks, routine_templates, "
    "categories, refresh_tokens, users"
)


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    asyncio.run(_reset_schema())
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


class ApiUser:
    """A registered user plus helpers for authenticated calls."""

    def __init__(self, client: AsyncClient, email: str, tokens: dict):
        self.client = client
        self.email = email
        self.tokens = tokens

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}

    async def get(self, url: str, **kw):
        return await self.client.get(url, headers=self.headers, **kw)

    async def post(self, url: str, **kw):
        return await self.client.post(url, headers=self.headers, **kw)

    async def patch(self, url: str, **kw):
        return await self.client.patch(url, headers=self.headers, **kw)

    async def put(self, url: str, **kw):
        return await self.client.put(url, headers=self.headers, **kw)

    async def delete(self, url: str, **kw):
        return await self.client.delete(url, headers=self.headers, **kw)

    async def category_id(self, name: str) -> str:
        resp = await self.get("/api/v1/categories")
        return next(c["id"] for c in resp.json() if c["name"] == name)


@pytest.fixture
def make_user(client: AsyncClient):
    async def _make(email: str = "mayur@example.com", timezone: str = "UTC") -> ApiUser:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "correct horse battery",
                "display_name": email.split("@")[0],
                "timezone": timezone,
            },
        )
        assert resp.status_code == 201, resp.text
        return ApiUser(client, email, resp.json())

    return _make
