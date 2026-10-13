"""Small fixtures shared by the platform and price alert tests."""

import asyncio
from unittest.mock import Mock

import pytest

import bot_application
import price_alerts
from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext


@pytest.fixture
def market_quote():
    def quote(price, change=0):
        return {
            "data": {
                "42": {"quote": {"USD": {"price": price, "percent_change_24h": change}}}
            }
        }

    return quote


@pytest.fixture
def market_lookup(monkeypatch, market_quote):
    lookup = Mock(return_value=market_quote(10))
    monkeypatch.setattr(bot_application, "get_coin_data", lookup)
    monkeypatch.setattr(price_alerts, "get_coin_data", lookup)
    return lookup


@pytest.fixture
def discord_context():
    return CommandContext(Backend.DISCORD, "8", "123", "Ada O'Neil")


@pytest.fixture
def application(tmp_path, market_lookup):
    return BotApplication(
        {"TST": {"cmc_id": "42"}},
        "cmc-key",
        crypto_path=tmp_path / "cryptos.json",
        notification_path=tmp_path / "discord_notifications.db",
    )


@pytest.fixture
def alerts(application):
    return application.price_alerts


@pytest.fixture
def run_async():
    # Keep one event loop per test so background tasks can be closed on that loop.
    with asyncio.Runner() as runner:
        yield runner.run
