"""Read the selected chat platform from BOT_BACKEND."""

from __future__ import annotations

import os
from enum import StrEnum


class Backend(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"


def get_backend(value: str | None = None) -> Backend:
    """Default to Telegram to preserve existing deployments."""
    configured_value = value if value is not None else os.getenv("BOT_BACKEND")
    normalized_value = (configured_value or Backend.TELEGRAM.value).strip().lower()

    try:
        return Backend(normalized_value)
    except ValueError as error:
        supported = ", ".join(backend.value for backend in Backend)
        raise ValueError(f"BOT_BACKEND must be one of: {supported}; got {normalized_value!r}") from error
