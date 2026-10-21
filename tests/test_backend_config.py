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


@pytest.mark.parametrize(
    ("backend", "module_name"),
    [(Backend.TELEGRAM, "telegram_bot"), (Backend.DISCORD, "discord_bot")],
    ids=["telegram", "discord"],
)
def test_main_starts_selected_backend(monkeypatch, backend, module_name):
    starts = []
    module = ModuleType(module_name)
    module.run = lambda: starts.append(backend)
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setattr(main, "get_backend", lambda: backend)

    main.main()

    assert starts == [backend]
