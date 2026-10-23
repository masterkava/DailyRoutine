import enum

from sqlalchemy import Enum


class CategoryKind(enum.StrEnum):
    productive = "productive"
    maintenance = "maintenance"
    leisure = "leisure"
    wasted = "wasted"


class LogStatus(enum.StrEnum):
    open = "open"
    closed = "closed"


class EntrySource(enum.StrEnum):
    planned = "planned"
    adjusted = "adjusted"
    manual = "manual"
    timer = "timer"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Native Postgres enum that stores the member *values* (lower-case strings)."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])
