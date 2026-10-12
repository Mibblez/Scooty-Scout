from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime as DateTime
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest
from requests.exceptions import (
    ConnectionError,
    RequestException,
    Timeout,
    TooManyRedirects,
)

import bot_utilities
import globals


class Coin(TypedDict):
    id: int
    symbol: str


type CoinMarketCapResponse = dict[str, list[Coin] | dict[str, Coin]]


class SessionCall(TypedDict):
    url: str
    params: dict[str, str]
    headers: dict[str, str]


class RecordingBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))


class FakeResponse:
    """Provide the response text expected by API helper tests."""

    def __init__(self, text: str) -> None:
        self.text = text


class FakeSession:
    """Record API requests and return configurable responses or request errors."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[SessionCall] = []
        self.payload: CoinMarketCapResponse = {"data": [{"id": 1, "symbol": "BTC"}]}
        self.error: RequestException | None = None

    def get(self, url: str, params: dict[str, str]) -> FakeResponse:
        self.calls.append(
            {"url": url, "params": params.copy(), "headers": self.headers.copy()}
        )
        if self.error is not None:
            raise self.error
        return FakeResponse(json.dumps(self.payload))


@pytest.fixture
def recording_bot(monkeypatch: pytest.MonkeyPatch) -> RecordingBot:
    bot = RecordingBot()
    monkeypatch.setattr(globals, "bot", bot, raising=False)
    monkeypatch.setattr(
        globals, "cryptos_json", {"BTC": {}, "ETH": {}}, raising=False
    )
    return bot


@pytest.fixture
def mock_session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    session = FakeSession()

    def create_session() -> FakeSession:
        return session

    monkeypatch.setattr(bot_utilities, "Session", create_session)
    return session


@pytest.fixture
def fixed_log_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls: type[FixedDateTime]) -> DateTime:
            return DateTime(2026, 10, 11, 12, 34, 56)

    monkeypatch.setattr(bot_utilities, "datetime", FixedDateTime)


def test_user_state_starts_at_zero_and_tracks_current_command() -> None:
    """Verify a new command state has the expected defaults and representation."""
    state: bot_utilities.UserState = bot_utilities.UserState("new_crypto")

    assert state.current_command == "new_crypto"
    assert state.state == 0
    assert state.new_crypto_tmp is None
    assert state.additional_info is None
    assert repr(state) == "new_crypto-0"

    state.state = 2
    assert repr(state) == "new_crypto-2"


def test_usage_error_sends_usage_to_message_chat(recording_bot: RecordingBot) -> None:
    """Verify usage errors are sent to the originating chat."""
    message: SimpleNamespace = SimpleNamespace(chat=SimpleNamespace(id=42))

    bot_utilities.usage_error(message, "/price COIN")

    assert recording_bot.messages == [(42, "Usage\n/price COIN")]


def test_unknown_coin_lists_known_symbols(recording_bot: RecordingBot) -> None:
    """Verify unknown-coin replies include the configured coin symbols."""
    message: SimpleNamespace = SimpleNamespace(chat=SimpleNamespace(id=42))

    bot_utilities.unknown_coin(message, "DOGE")

    assert recording_bot.messages == [
        (42, "Unknown coin: DOGE\n\nKnown coins:BTC ; ETH")
    ]


def test_log_to_disk_writes_timestamp_and_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_log_time: None
) -> None:
    """Verify log entries include a timestamp and command name."""
    monkeypatch.chdir(tmp_path)

    bot_utilities.log_to_disk("Started", "/start")

    assert (tmp_path / "botlog.log").read_text(encoding="utf-8") == (
        "[2026-10-11 12:34:56](/start)Started\n"
    )


def test_log_to_disk_includes_user_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_log_time: None
) -> None:
    """Verify user identity is added to logs when a message is provided."""
    message: SimpleNamespace = SimpleNamespace(
        from_user=SimpleNamespace(id=7, first_name="Ada", last_name="Lovelace")
    )
    monkeypatch.chdir(tmp_path)

    bot_utilities.log_to_disk("Added BTC", "/new_crypto", message)

    assert (tmp_path / "botlog.log").read_text(encoding="utf-8") == (
        "[2026-10-11 12:34:56](/new_crypto){Ada Lovelace - 7} Added BTC\n"
    )


def test_log_to_disk_preserves_existing_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_log_time: None
) -> None:
    """Verify successive log calls append entries without losing earlier logs."""
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / "botlog.log"
    log_path.write_text("Existing entry\n", encoding="utf-8")

    bot_utilities.log_to_disk("First", "/start")
    bot_utilities.log_to_disk("Second", "/price")

    assert log_path.read_text(encoding="utf-8") == (
        "Existing entry\n"
        "[2026-10-11 12:34:56](/start)First\n"
        "[2026-10-11 12:34:56](/price)Second\n"
    )


def test_get_coin_data_sends_api_key_and_coin_id(
    mock_session: FakeSession,
) -> None:
    """Verify quote requests include the API key and requested coin ID."""
    mock_session.payload = {"data": {"1": {"id": 1, "symbol": "BTC"}}}
    result: CoinMarketCapResponse = bot_utilities.get_coin_data("1", "test-api-key")

    assert result == mock_session.payload
    assert mock_session.calls == [
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
    ids=["contract-address", "coin-id"],
)
def test_get_coin_info_uses_address_or_id(
    mock_session: FakeSession,
    coin_id: str | None,
    expected_params: dict[str, str],
) -> None:
    """Verify info requests query by contract address or CoinMarketCap ID."""
    mock_session.payload = {"data": {"1234": {"id": 1234, "symbol": "TEST"}}}
    result: CoinMarketCapResponse = bot_utilities.get_coin_info(
        "0xabc", "test-api-key", id=coin_id
    )

    assert result == mock_session.payload
    assert mock_session.calls == [
        {
            "url": "https://pro-api.coinmarketcap.com/v1/cryptocurrency/info",
            "params": expected_params,
            "headers": {
                "Accepts": "application/json",
                "X-CMC_PRO_API_KEY": "test-api-key",
            },
        }
    ]


def test_cmc_id_map_queries_by_symbol(mock_session: FakeSession) -> None:
    """Verify the CoinMarketCap map endpoint is queried by symbol."""
    result: CoinMarketCapResponse = bot_utilities.cmc_id_map("BTC", "test-api-key")

    assert result == {"data": [{"id": 1, "symbol": "BTC"}]}
    assert mock_session.calls == [
        {
            "url": "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map",
            "params": {"symbol": "BTC"},
            "headers": {
                "Accepts": "application/json",
                "X-CMC_PRO_API_KEY": "test-api-key",
            },
        }
    ]


@pytest.mark.parametrize(
    "fetch_coin",
    [bot_utilities.get_coin_data, bot_utilities.get_coin_info, bot_utilities.cmc_id_map],
    ids=["quotes", "info", "map"],
)
@pytest.mark.parametrize(
    "error_type",
    [ConnectionError, Timeout, TooManyRedirects],
    ids=["connection-error", "timeout", "redirect-limit"],
)
def test_cmc_request_failure_returns_none(
    mock_session: FakeSession,
    fetch_coin: Callable[[str, str], object],
    error_type: type[RequestException],
) -> None:
    """Verify each API helper handles request failures without a response object."""
    mock_session.error = error_type("Request failed")

    assert fetch_coin("BTC", "test-api-key") is None
    assert len(mock_session.calls) == 1
