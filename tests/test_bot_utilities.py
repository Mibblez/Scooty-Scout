import json
from datetime import datetime as DateTime
from types import SimpleNamespace

import pytest

import bot_utilities
import globals


class RecordingBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.fixture
def recording_bot(monkeypatch):
    bot = RecordingBot()
    monkeypatch.setattr(globals, "bot", bot, raising=False)
    monkeypatch.setattr(
        globals, "cryptos_json", {"BTC": {}, "ETH": {}}, raising=False
    )
    return bot


@pytest.fixture
def mock_session(monkeypatch):
    calls = []

    class FakeResponse:
        text = json.dumps({"data": [{"id": 1, "symbol": "BTC"}]})

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, params):
            calls.append(
                {"url": url, "params": params, "headers": self.headers.copy()}
            )
            return FakeResponse()

    monkeypatch.setattr(bot_utilities, "Session", FakeSession)
    return calls


def test_user_state_starts_at_zero_and_tracks_current_command():
    """Verify a new command state has the expected defaults and representation."""
    state = bot_utilities.UserState("new_crypto")

    assert state.current_command == "new_crypto"
    assert state.state == 0
    assert state.new_crypto_tmp is None
    assert state.additional_info is None
    assert repr(state) == "new_crypto-0"

    state.state = 2
    assert repr(state) == "new_crypto-2"


def test_usage_error_sends_usage_to_message_chat(recording_bot):
    """Verify usage errors are sent to the originating chat."""
    message = SimpleNamespace(chat=SimpleNamespace(id=42))

    bot_utilities.usage_error(message, "/price COIN")

    assert recording_bot.messages == [(42, "Usage\n/price COIN")]


def test_unknown_coin_lists_known_symbols(recording_bot):
    """Verify unknown-coin replies include the configured coin symbols."""
    message = SimpleNamespace(chat=SimpleNamespace(id=42))

    bot_utilities.unknown_coin(message, "DOGE")

    assert recording_bot.messages == [
        (42, "Unknown coin: DOGE\n\nKnown coins:BTC ; ETH")
    ]


def test_log_to_disk_writes_timestamp_and_command(tmp_path, monkeypatch):
    """Verify log entries include a timestamp and command name."""
    class FixedDateTime:
        @classmethod
        def now(cls):
            return DateTime(2026, 10, 11, 12, 34, 56)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_utilities, "datetime", FixedDateTime)

    bot_utilities.log_to_disk("Started", "/start")

    assert (tmp_path / "botlog.log").read_text(encoding="utf-8") == (
        "[2026-10-11 12:34:56](/start)Started\n"
    )


def test_log_to_disk_includes_user_details(tmp_path, monkeypatch):
    """Verify user identity is added to logs when a message is provided."""
    class FixedDateTime:
        @classmethod
        def now(cls):
            return DateTime(2026, 10, 11, 12, 34, 56)

    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7, first_name="Ada", last_name="Lovelace")
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bot_utilities, "datetime", FixedDateTime)

    bot_utilities.log_to_disk("Added BTC", "/new_crypto", message)

    assert (tmp_path / "botlog.log").read_text(encoding="utf-8") == (
        "[2026-10-11 12:34:56](/new_crypto){Ada Lovelace - 7} Added BTC\n"
    )


def test_get_coin_data_sends_api_key_and_coin_id(mock_session):
    """Verify quote requests include the API key and requested coin ID."""
    result = bot_utilities.get_coin_data("1", "test-api-key")

    assert result == {"data": [{"id": 1, "symbol": "BTC"}]}
    assert mock_session == [
        {
            "url": "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
            "params": {"id": "1"},
            "headers": {
                "Accepts": "application/json",
                "X-CMC_PRO_API_KEY": "test-api-key",
            },
        }
    ]


@pytest.mark.parametrize(
    ("coin_id", "expected_params"),
    [(None, {"address": "0xabc"}), ("1234", {"id": "1234"})],
)
def test_get_coin_info_uses_address_or_id(mock_session, coin_id, expected_params):
    """Verify info requests query by contract address or CoinMarketCap ID."""
    result = bot_utilities.get_coin_info("0xabc", "test-api-key", id=coin_id)

    assert result == {"data": [{"id": 1, "symbol": "BTC"}]}
    assert mock_session[0]["url"] == (
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/info"
    )
    assert mock_session[0]["params"] == expected_params


def test_cmc_id_map_queries_by_symbol(mock_session):
    """Verify the CoinMarketCap map endpoint is queried by symbol."""
    result = bot_utilities.cmc_id_map("BTC", "test-api-key")

    assert result == {"data": [{"id": 1, "symbol": "BTC"}]}
    assert mock_session[0]["url"] == (
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
    )
    assert mock_session[0]["params"] == {"symbol": "BTC"}
