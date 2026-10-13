from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TypedDict

import pytest
from requests.exceptions import (
    ConnectionError,
    RequestException,
    Timeout,
    TooManyRedirects,
)

import bot_utilities
from backend_config import Backend
from command_context import CommandContext
from logging_setup import configure_logging


class Coin(TypedDict):
    id: int
    symbol: str


type CoinMarketCapResponse = dict[str, list[Coin] | dict[str, Coin]]


class SessionCall(TypedDict):
    url: str
    params: dict[str, str]
    headers: dict[str, str]


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
        self.timeout: int | None = None

    def get(self, url: str, params: dict[str, str], timeout: int | None = None) -> FakeResponse:
        self.timeout = timeout
        self.calls.append(
            {"url": url, "params": params.copy(), "headers": self.headers.copy()}
        )
        if self.error is not None:
            raise self.error
        return FakeResponse(json.dumps(self.payload))


@pytest.fixture
def mock_session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    session = FakeSession()

    def create_session() -> FakeSession:
        return session

    monkeypatch.setattr(bot_utilities, "Session", create_session)
    return session


@pytest.fixture
def log_file(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "botlog.log"
    try:
        yield path
    finally:
        logger = logging.getLogger("scooty_scout")
        for handler in logger.handlers[:]:
            if handler.name in {"scooty_scout_file", "scooty_scout_terminal"}:
                logger.removeHandler(handler)
                handler.close()


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


def test_usage_error_formats_message() -> None:
    assert bot_utilities.usage_error("/price COIN") == "Usage\n/price COIN"


def test_unknown_coin_lists_known_symbols() -> None:
    assert bot_utilities.unknown_coin("DOGE", ["BTC", "ETH"]) == (
        "Unknown coin: DOGE\n\nKnown coins:BTC ; ETH"
    )


def test_log_to_disk_writes_timestamp_and_command(
    log_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify log entries include a timestamp and command name."""
    configure_logging(log_file)
    bot_utilities.log_to_disk("Started", "/start")

    entry = log_file.read_text(encoding="utf-8")
    assert re.fullmatch(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] INFO \(/start\)Started\n",
        entry,
    )
    assert capsys.readouterr().err == entry


def test_log_to_disk_includes_user_details(
    log_file: Path,
) -> None:
    """Verify platform-neutral actor identity is added to logs."""
    configure_logging(log_file)
    actor = CommandContext(
        backend=Backend.TELEGRAM,
        user_id="7",
        conversation_id="7",
        display_name="Ada Lovelace",
    )
    bot_utilities.log_to_disk("Added BTC", "/new_crypto", actor)

    assert log_file.read_text(encoding="utf-8").endswith(
        "INFO (/new_crypto){Ada Lovelace - 7} Added BTC\n"
    )


def test_log_to_disk_preserves_existing_entries(
    log_file: Path,
) -> None:
    """Verify successive log calls append entries without losing earlier logs."""
    configure_logging(log_file)
    bot_utilities.log_to_disk("First", "/start")
    bot_utilities.log_to_disk("Second", "/price")

    entries = log_file.read_text(encoding="utf-8").splitlines()
    assert len(entries) == 2
    assert entries[0].endswith("INFO (/start)First")
    assert entries[1].endswith("INFO (/price)Second")


def test_logging_rotates_at_ten_megabytes(log_file: Path) -> None:
    """Verify the configured log size and retention without writing a large file."""
    logger = configure_logging(log_file)
    file_handlers = [
        handler for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler)
    ]

    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 10_000_000
    assert file_handlers[0].backupCount == 3
    initial_handlers = logger.handlers[:]
    assert configure_logging(log_file) is logger
    assert logger.handlers == initial_handlers


def test_get_coin_data_sends_api_key_and_coin_id(
    mock_session: FakeSession,
) -> None:
    """Verify quote requests include the API key and requested coin ID."""
    mock_session.payload = {"data": {"1": {"id": 1, "symbol": "BTC"}}}
    result: CoinMarketCapResponse = bot_utilities.get_coin_data("1", "test-api-key")

    assert result == mock_session.payload
    assert mock_session.timeout == 15
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
