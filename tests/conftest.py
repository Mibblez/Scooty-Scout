"""Small fixtures shared by the platform and price alert tests."""

import asyncio
from unittest.mock import Mock

import pytest

import bot_application
import price_alerts
from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext
from ethereum_gas import GasEstimate, GasPrices
from media_commands import MediaCommands


@pytest.fixture
def moon_audio(tmp_path):
    path = tmp_path / "wen_moon.ogg"
    path.write_bytes(b"OggS test audio")
    return path


@pytest.fixture
def gas_prices():
    return GasPrices(
        [GasEstimate("Safe", 1.25, 0.38), GasEstimate("Proposed", 2, 0.608), GasEstimate("Fast", 3, 0.912)]
    )


@pytest.fixture
def market_quote():
    def quote(price, change=0):
        return {"data": {"42": {"quote": {"USD": {"price": price, "percent_change_24h": change}}}}}

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
    )


@pytest.fixture
def media_application(application, tmp_path):
    application.media_commands = MediaCommands(tmp_path / "discord_media")
    return application


@pytest.fixture
def video_download(monkeypatch):
    download = Mock(return_value=b"video")
    monkeypatch.setattr(bot_application, "download_twitter_video", download)
    return download


@pytest.fixture
def alert_application(application, tmp_path):
    application.price_alerts = price_alerts.PriceAlerts(
        application.cryptos, application.cmc_api_key, tmp_path / "discord_notifications.db"
    )
    return application


@pytest.fixture
def alerts(alert_application):
    return alert_application.price_alerts


@pytest.fixture
def run_async():
    # Keep one event loop per test so background tasks can be closed on that loop.
    with asyncio.Runner() as runner:
        yield runner.run
