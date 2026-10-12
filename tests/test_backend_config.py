"""Tests for chat-platform selection."""

import pytest

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
