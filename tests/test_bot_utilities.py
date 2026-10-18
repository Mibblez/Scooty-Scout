import json
import logging
import re
from logging.handlers import RotatingFileHandler

import pytest
from requests.exceptions import (
    ConnectionError,
    Timeout,
    TooManyRedirects,
)

import bot_utilities
from backend_config import Backend
from command_context import CommandContext
from logging_setup import configure_logging


class FakeResponse:
    """Provide the response text expected by API helper tests."""

    def __init__(self, text):
        self.text = text


class FakeSession:
    """Record API requests and return configurable responses or request errors."""

    def __init__(self):
        self.headers = {}
        self.calls = []
        self.payload = {"data": [{"id": 1, "symbol": "BTC"}]}
        self.error = None
        self.timeout = None

    def get(self, url, params, timeout=None):
        self.timeout = timeout
        self.calls.append({"url": url, "params": params.copy(), "headers": self.headers.copy()})
        if self.error is not None:
            raise self.error
        return FakeResponse(json.dumps(self.payload))


@pytest.fixture
def mock_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(bot_utilities, "Session", lambda: session)
    return session


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "botlog.log"
    try:
        yield path
    finally:
        logger = logging.getLogger("scooty_scout")
        for handler in logger.handlers[:]:
            if handler.name in {"scooty_scout_file", "scooty_scout_terminal"}:
                logger.removeHandler(handler)
                handler.close()


def test_user_state_starts_at_zero_and_tracks_current_command():
    state = bot_utilities.UserState("new_crypto")

    assert state.current_command == "new_crypto"
    assert state.state == 0
    assert state.new_crypto_tmp is None
    assert state.additional_info is None
    assert repr(state) == "new_crypto-0"

    state.state = 2
    assert repr(state) == "new_crypto-2"


def test_usage_error_formats_message():
    assert bot_utilities.usage_error("/price COIN") == "Usage\n/price COIN"


def test_unknown_coin_lists_known_symbols():
    assert bot_utilities.unknown_coin("DOGE", ["BTC", "ETH"]) == "Unknown coin: DOGE\n\nKnown coins:BTC ; ETH"


def test_log_entry_includes_timestamp_command_actor_and_terminal_output(log_file, capsys):
    configure_logging(log_file)
    actor = CommandContext(Backend.TELEGRAM, "7", "7", "Ada Lovelace")
    bot_utilities.log_to_disk("Added BTC", "/new_crypto", actor)

    entry = log_file.read_text(encoding="utf-8")
    assert re.fullmatch(
        r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] INFO \(/new_crypto\)\{Ada Lovelace - 7\} Added BTC\n",
        entry,
    )
    assert capsys.readouterr().err == entry


def test_log_to_disk_preserves_existing_entries(log_file):
    configure_logging(log_file)
    bot_utilities.log_to_disk("First", "/start")
    bot_utilities.log_to_disk("Second", "/price")

    entries = log_file.read_text(encoding="utf-8").splitlines()
    assert len(entries) == 2
    assert entries[0].endswith("INFO (/start)First")
    assert entries[1].endswith("INFO (/price)Second")


def test_logging_rotates_at_ten_megabytes(log_file):
    logger = configure_logging(log_file)
    file_handlers = [handler for handler in logger.handlers if isinstance(handler, RotatingFileHandler)]

    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 10_000_000
    assert file_handlers[0].backupCount == 3
    initial_handlers = logger.handlers[:]
    assert configure_logging(log_file) is logger
    assert logger.handlers == initial_handlers


def test_get_coin_data_sends_api_key_and_coin_id(mock_session):
    mock_session.payload = {"data": {"1": {"id": 1, "symbol": "BTC"}}}
    result = bot_utilities.get_coin_data("1", "test-api-key")

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
def test_get_coin_info_uses_address_or_id(mock_session, coin_id, expected_params):
    mock_session.payload = {"data": {"1234": {"id": 1234, "symbol": "TEST"}}}
    result = bot_utilities.get_coin_info("0xabc", "test-api-key", id=coin_id)

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


def test_cmc_id_map_queries_by_symbol(mock_session):
    result = bot_utilities.cmc_id_map("BTC", "test-api-key")

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
def test_cmc_request_failure_returns_none(mock_session, fetch_coin, error_type):
    mock_session.error = error_type("Request failed")

    assert fetch_coin("BTC", "test-api-key") is None
    assert len(mock_session.calls) == 1
