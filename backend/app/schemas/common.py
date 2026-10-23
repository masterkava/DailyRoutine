from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, ConfigDict
from pydantic import BaseModel as _BaseModel


class BaseModel(_BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA timezone: {value!r}") from exc
    return value


TimezoneName = Annotated[str, AfterValidator(_validate_timezone)]
