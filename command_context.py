"""Platform-neutral identity for a command invocation."""

from dataclasses import dataclass

from backend_config import Backend


@dataclass(frozen=True)
class CommandContext:
    backend: Backend
    user_id: str
    conversation_id: str
    display_name: str
