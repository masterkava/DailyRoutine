from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Life Mirror API"
    database_url: str = "postgresql+asyncpg://lifemirror:lifemirror@localhost:5432/lifemirror"
    test_database_url: str = (
        "postgresql+asyncpg://lifemirror:lifemirror@localhost:5432/lifemirror_test"
    )
    sql_echo: bool = False

    jwt_secret: str = "dev-insecure-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
