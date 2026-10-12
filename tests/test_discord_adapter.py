"""Discord command boundary tests without a live Discord connection."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bot_application
from bot_application import BotApplication, CoinCandidate, CoinCreationError
from backend_config import Backend
from command_context import CommandContext
from discord_adapter import DiscordAdapter
from discord_bot import _admin_ids


def test_coin_creation_is_shared_and_persisted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    crypto_path = tmp_path / "cryptos.json"
    crypto_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        bot_application,
        "cmc_id_map",
        lambda symbol, key: {"status": {"error_message": None}, "data": [{"id": 42}]},
    )
    monkeypatch.setattr(
        bot_application,
        "get_coin_info",
        lambda address, key, id: {
            "status": {"error_message": None},
            "data": {"42": {
                "symbol": "TST", "name": "Test Coin",
                "urls": {"website": ["https://example.com"]}, "platform": None,
            }},
        },
    )
    application = BotApplication({}, "cmc-key", crypto_path)

    candidate = application.prepare_new_coin("tst")
    application.add_coin(candidate)

    assert application.coins(CommandContext(Backend.DISCORD, "7", "123", "Ada")) == "Known coins:\nTST"
    assert json.loads(crypto_path.read_text(encoding="utf-8"))["TST"]["cmc_id"] == "42"
    with pytest.raises(CoinCreationError, match="already known"):
        application.add_coin(candidate)


def test_discord_new_crypto_requires_admin_and_confirms(tmp_path: Path) -> None:
    crypto_path = tmp_path / "cryptos.json"
    crypto_path.write_text("{}", encoding="utf-8")
    application = BotApplication({}, "cmc-key", crypto_path)
    candidate = CoinCandidate("TST", "Test Coin", "42", "https://example.com", None, None)
    application.prepare_new_coin = lambda identifier: candidate
    adapter = DiscordAdapter(application, {7}, 123)
    command = adapter.tree.get_command("new_crypto")
    calls = []

    async def send_message(*args, **kwargs):
        calls.append(("send", args, kwargs))

    async def defer(**kwargs):
        calls.append(("defer", (), kwargs))

    async def followup_send(*args, **kwargs):
        calls.append(("followup", args, kwargs))

    async def edit_message(**kwargs):
        calls.append(("edit", (), kwargs))

    def interaction(user_id):
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id, display_name="Ada"),
            channel_id=123,
            response=SimpleNamespace(send_message=send_message, defer=defer,
                                     edit_message=edit_message),
            followup=SimpleNamespace(send=followup_send),
        )

    asyncio.run(command.callback(interaction(8), "TST"))
    assert calls[-1][2]["ephemeral"] is True
    assert "Only admins" in calls[-1][1][0]

    asyncio.run(command.callback(interaction(7), "TST"))
    assert calls[-1][0] == "followup"
    view = calls[-1][2]["view"]
    asyncio.run(view.children[0].callback(interaction(7)))

    assert calls[-1][0] == "edit"
    assert "has been added" in calls[-1][2]["content"]
    assert "TST" in json.loads(crypto_path.read_text(encoding="utf-8"))


def test_discord_admin_ids_must_be_configured() -> None:
    assert _admin_ids("[7, 8]") == {7, 8}
    with pytest.raises(ValueError, match="nonempty"):
        _admin_ids("[]")
