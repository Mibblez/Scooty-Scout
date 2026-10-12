"""Tests for chat-platform selection."""

import sys
from types import ModuleType

import pytest

import main
from backend_config import Backend, get_backend


def test_backend_defaults_to_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_BACKEND", raising=False)

    assert get_backend() is Backend.TELEGRAM


@pytest.mark.parametrize(
    ("value", "expected"),
    [("telegram", Backend.TELEGRAM), ("DISCORD", Backend.DISCORD)],
)
def test_backend_accepts_supported_values(value: str, expected: Backend) -> None:
    assert get_backend(value) is expected


def test_backend_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="BOT_BACKEND must be one of: telegram, discord"):
        get_backend("matrix")


def test_main_starts_telegram_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    starts: list[str] = []
    telegram_module = ModuleType("telegram_bot")
    telegram_module.run = lambda: starts.append("telegram")
    monkeypatch.setitem(sys.modules, "telegram_bot", telegram_module)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setattr(main, "get_backend", lambda: Backend.TELEGRAM)

    main.main()

    assert starts == ["telegram"]


def test_main_starts_discord_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    starts: list[str] = []
    discord_module = ModuleType("discord_bot")
    discord_module.run = lambda: starts.append("discord")
    monkeypatch.setitem(sys.modules, "discord_bot", discord_module)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setattr(main, "get_backend", lambda: Backend.DISCORD)

    main.main()

    assert starts == ["discord"]
