"""Store reusable media commands independently of any chat platform."""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

MAX_MEDIA_BYTES = 8 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class MediaCommandError(ValueError):
    """A custom media command cannot be created or found."""


def _label(value: str, description: str) -> str:
    if not isinstance(value, str):
        raise MediaCommandError(f"Invalid {description}.")
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value):
        raise MediaCommandError(
            f"{description.capitalize()} must be 1–32 letters, digits, underscores, or hyphens, "
            "starting with a letter or digit."
        )
    return value


@dataclass(frozen=True)
class MediaCommand:
    name: str
    group: str
    filename: str

    @property
    def media_type(self) -> str:
        return "video" if self.filename.endswith(".mp4") else "image"


class MediaCommands:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        self.catalog_path = self.directory / "commands.json"
        self._lock = Lock()
        self._commands: dict[str, MediaCommand] = {}
        if self.catalog_path.exists():
            try:
                records = json.loads(self.catalog_path.read_text(encoding="utf-8"))
                if not isinstance(records, dict):
                    raise ValueError("Expected a command catalog.")
                for name, record in records.items():
                    command = self.prepare(name, record["filename"], record["group"])
                    if name != command.name or record["filename"] != command.filename:
                        raise ValueError("Invalid saved command name or filename.")
                    self._commands[name] = command
            except (KeyError, TypeError, ValueError) as error:
                raise MediaCommandError(f"Invalid media command catalog: {self.catalog_path}") from error

    def commands(self) -> tuple[MediaCommand, ...]:
        with self._lock:
            return tuple(sorted(self._commands.values(), key=lambda command: command.name))

    def prepare(self, name: str, filename: str, group: str, size: int | None = None) -> MediaCommand:
        name = _label(name, "command name")
        group = _label(group, "group name")
        extension = Path(filename).suffix.lower()
        if extension not in IMAGE_EXTENSIONS | {".mp4"}:
            raise MediaCommandError("Use a PNG, JPEG, GIF, or WebP image, or an MP4 video.")
        if size is not None and not 0 < size <= MAX_MEDIA_BYTES:
            raise MediaCommandError("Media must be non-empty and at most 8 MiB.")
        if name in self._commands:
            raise MediaCommandError(f"Cannot create /{name}. Command already exists.")
        return MediaCommand(name, group, f"{name}{extension}")

    def add(self, command: MediaCommand, content: bytes) -> None:
        with self._lock:
            command = self.prepare(command.name, command.filename, command.group, len(content))
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / command.filename
            updated = {**self._commands, command.name: command}
            created = False
            try:
                with path.open("xb") as output:
                    created = True
                    output.write(content)
                self._save(updated)
            except BaseException:
                if created:
                    path.unlink(missing_ok=True)
                raise
            self._commands = updated

    def list_commands(self, group: str | None = None) -> str:
        commands = self.commands()
        if not commands:
            return "No custom media commands have been added yet."
        if group is not None:
            group = _label(group, "group name")
            selected = [command for command in commands if command.group == group]
            if not selected:
                known = ", ".join(sorted({command.group for command in commands}))
                raise MediaCommandError(f"Unknown command group: {group}. Known groups: {known}")
            return f"Custom commands in {group}:\n" + "\n".join(f"/{command.name}" for command in selected)
        lines = ["Custom media commands:"]
        for name in sorted({command.group for command in commands}):
            names = ", ".join(f"/{command.name}" for command in commands if command.group == name)
            lines.append(f"{name}: {names}")
        return "\n".join(lines)

    def _save(self, commands: dict[str, MediaCommand]) -> None:
        records = {name: {"group": command.group, "filename": command.filename} for name, command in commands.items()}
        descriptor, temporary_path = tempfile.mkstemp(prefix=".commands-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(records, output, indent=4)
            os.replace(temporary_path, self.catalog_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
