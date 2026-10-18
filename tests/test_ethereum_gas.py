"""Ethereum gas lookups and calculations without live API calls."""

from unittest.mock import MagicMock, Mock

import pytest
from requests.exceptions import HTTPError, Timeout

import ethereum_gas
from ethereum_gas import GasPriceError


def etherscan_response(result, status="1"):
    response = Mock()
    response.json.return_value = {"status": status, "result": result}
    return response


@pytest.fixture
def gas_api(monkeypatch):
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = [
        etherscan_response({"SafeGasPrice": "1.25", "ProposeGasPrice": "2", "FastGasPrice": "3"}),
        etherscan_response({"ethusd": "2000"}),
    ]
    monkeypatch.setattr(ethereum_gas, "Session", Mock(return_value=session))
    return session


def test_ethgas_uses_v2_and_calculates_usd_estimates(application, discord_context, gas_api):
    application.etherscan_api_key = "etherscan-key"

    prices = application.ethgas(discord_context)

    assert prices.gas_limit == 152_000
    assert [estimate.usd for estimate in prices.estimates] == pytest.approx([0.38, 0.608, 0.912])
    assert prices.as_text() == (
        "Uniswap gas estimate (152,000 gas limit)\n"
        "Safe: 1.25 gwei ($0.3800)\n"
        "Proposed: 2 gwei ($0.6080)\n"
        "Fast: 3 gwei ($0.9120)"
    )
    assert gas_api.get.call_count == 2
    endpoints = [("gastracker", "gasoracle"), ("stats", "ethprice")]
    for request, (module, action) in zip(gas_api.get.call_args_list, endpoints):
        assert request.args == ("https://api.etherscan.io/v2/api",)
        assert request.kwargs == {
            "params": {"chainid": "1", "module": module, "action": action, "apikey": "etherscan-key"},
            "timeout": 15,
        }


def test_ethgas_requires_a_key_without_making_requests(application, discord_context, gas_api):
    with pytest.raises(GasPriceError, match="Set ETHERSCAN_API_KEY"):
        application.ethgas(discord_context)

    gas_api.get.assert_not_called()


@pytest.mark.parametrize(
    ("method", "error"),
    [
        ("get", Timeout("Failed request with apikey=secret")),
        ("raise_for_status", HTTPError("HTTP 503")),
        ("json", ValueError("Invalid JSON")),
    ],
    ids=["timeout", "http-error", "invalid-json"],
)
def test_ethgas_handles_request_failures_without_logging_secrets(gas_api, caplog, method, error):
    response = etherscan_response({})
    if method == "get":
        failing_method = gas_api.get
    else:
        gas_api.get.side_effect = [response]
        failing_method = getattr(response, method)
    failing_method.side_effect = error

    with pytest.raises(GasPriceError, match="Could not get Ethereum gas prices"):
        ethereum_gas.get_ethereum_gas("secret")

    failing_method.assert_called_once()
    assert "secret" not in caplog.text


@pytest.mark.parametrize(
    ("result", "status"),
    [
        ("Max rate limit reached", "0"),
        ({}, "1"),
        ({"SafeGasPrice": "NaN", "ProposeGasPrice": "2", "FastGasPrice": "3"}, "1"),
    ],
    ids=["api-rejection", "missing-values", "invalid-number"],
)
def test_ethgas_rejects_unsuccessful_or_invalid_results(gas_api, result, status):
    gas_api.get.side_effect = [etherscan_response(result, status), etherscan_response({"ethusd": "2000"})]

    with pytest.raises(GasPriceError, match="Could not get Ethereum gas prices"):
        ethereum_gas.get_ethereum_gas("etherscan-key")
