"""Fetch Ethereum gas estimates without depending on a chat platform."""

import logging
import math
from dataclasses import dataclass

from requests import Session
from requests.exceptions import RequestException

logger = logging.getLogger("scooty_scout")
UNISWAP_GAS_LIMIT = 152_000


class GasPriceError(ValueError):
    """Ethereum gas prices are not configured or could not be retrieved."""


@dataclass(frozen=True)
class GasEstimate:
    label: str
    gwei: float
    usd: float

    def as_text(self) -> str:
        rate = f"{self.gwei:.9f}".rstrip("0").rstrip(".")
        return f"{rate} gwei (${self.usd:.4f})"


@dataclass(frozen=True)
class GasPrices:
    estimates: list[GasEstimate]
    gas_limit: int = UNISWAP_GAS_LIMIT

    def as_text(self) -> str:
        lines = [f"Uniswap gas estimate ({self.gas_limit:,} gas limit)"]
        lines.extend(f"{estimate.label}: {estimate.as_text()}" for estimate in self.estimates)
        return "\n".join(lines)


def _request_result(session: Session, api_key: str, module: str, action: str) -> dict:
    response = session.get(
        "https://api.etherscan.io/v2/api",
        params={"chainid": "1", "module": module, "action": action, "apikey": api_key},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "1" or not isinstance(payload.get("result"), dict):
        raise ValueError("Etherscan did not return a successful result.")
    return payload["result"]


def get_ethereum_gas(api_key: str | None) -> GasPrices:
    if not api_key or not api_key.strip():
        raise GasPriceError("Ethereum gas prices are not configured. Set ETHERSCAN_API_KEY to use /ethgas.")
    try:
        with Session() as session:
            gas = _request_result(session, api_key, "gastracker", "gasoracle")
            price = _request_result(session, api_key, "stats", "ethprice")
        eth_usd = float(price["ethusd"])
        if not math.isfinite(eth_usd) or eth_usd <= 0:
            raise ValueError("Invalid ETH price.")
        estimates = []
        for label, key in (("Safe", "SafeGasPrice"), ("Proposed", "ProposeGasPrice"), ("Fast", "FastGasPrice")):
            gwei = float(gas[key])
            usd = gwei / 1_000_000_000 * eth_usd * UNISWAP_GAS_LIMIT
            if not math.isfinite(gwei) or gwei < 0 or not math.isfinite(usd):
                raise ValueError("Invalid gas price.")
            estimates.append(GasEstimate(label, gwei, usd))
    except (RequestException, KeyError, TypeError, ValueError) as error:
        # Request exceptions can contain a URL with the API key; log only their type.
        logger.warning("Etherscan gas lookup failed: %s", type(error).__name__)
        raise GasPriceError(
            "Could not get Ethereum gas prices. Check your Etherscan API key and limits, then try again."
        ) from None
    return GasPrices(estimates)
