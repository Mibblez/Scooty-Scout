"""Shared bot behavior called by each chat-platform adapter."""

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from bot_utilities import cmc_id_map, get_coin_info
from command_context import CommandContext


class CoinCreationError(ValueError):
    """A requested coin cannot be added to the catalog."""


@dataclass(frozen=True)
class CoinCandidate:
    symbol: str
    name: str
    cmc_id: str
    website: str
    contract_id: str | None
    chain: str | None

    def preview(self) -> str:
        return (f"-- {self.contract_id or self.name} --\n"
                f"Name: {self.name}\nSymbol: {self.symbol}\n"
                f"Chain: {self.chain}")

    def record(self) -> dict[str, Any]:
        return {
            "INFO": {
                "contract_id": self.contract_id,
                "chain": self.chain,
                "website": self.website,
            },
            "cmc_id": self.cmc_id,
            "cmc_name": self.name,
        }


class BotApplication:
    def __init__(
        self,
        cryptos: Mapping[str, Any],
        cmc_api_key: str | None = None,
        crypto_path: str | Path = "cryptos.json",
    ) -> None:
        self.cryptos = dict(cryptos) if not isinstance(cryptos, dict) else cryptos
        self.cmc_api_key = cmc_api_key
        self.crypto_path = Path(crypto_path)
        self._catalog_lock = Lock()

    def coins(self, _context: CommandContext) -> str:
        """List known coins without depending on a platform's message API."""
        return 'Known coins:\n' + ' ; '.join(self.cryptos)

    def prepare_new_coin(self, identifier: str) -> CoinCandidate:
        """Look up one coin in CoinMarketCap and prepare it for confirmation."""
        identifier = identifier.strip()
        if not identifier:
            raise CoinCreationError("Provide a contract address or coin symbol.")
        if not self.cmc_api_key:
            raise CoinCreationError("CoinMarketCap API key is not configured.")

        if identifier.startswith('0x'):
            response = get_coin_info(identifier, self.cmc_api_key)
        else:
            mapping = cmc_id_map(identifier.upper(), self.cmc_api_key)
            if mapping is None:
                raise CoinCreationError("Could not reach CoinMarketCap. Try again later.")
            error = mapping.get('status', {}).get('error_message')
            if error:
                raise CoinCreationError(f"Could not add coin: {error}")
            matches = mapping.get('data') or []
            if len(matches) != 1:
                raise CoinCreationError(
                    f"Found {len(matches)} cryptocurrencies matching {identifier}. "
                    "Use a contract address to identify one coin."
                )
            response = get_coin_info(None, self.cmc_api_key, id=int(matches[0]['id']))

        if response is None:
            raise CoinCreationError("Could not reach CoinMarketCap. Try again later.")
        error = response.get('status', {}).get('error_message')
        if error:
            raise CoinCreationError(f"Could not add coin: {error}")
        data = response.get('data') or {}
        if len(data) != 1:
            raise CoinCreationError("CoinMarketCap did not return one coin. Use a contract address.")

        cmc_id, coin = next(iter(data.items()))
        symbol = coin['symbol'].upper()
        if symbol in self.cryptos:
            raise CoinCreationError(f"Cannot add coin. {symbol} is already known by the bot.")
        platform = coin.get('platform')
        chain = platform['symbol'] if platform else None
        contract_id = platform['token_address'] if platform else None
        if chain == 'ETH':
            chain = 'ETH ERC-20'
        elif chain == 'BNB':
            chain = 'BNB BEP20'
        websites = coin.get('urls', {}).get('website') or []
        return CoinCandidate(
            symbol=symbol,
            name=coin['name'],
            cmc_id=str(cmc_id),
            website=websites[0] if websites else '',
            contract_id=contract_id,
            chain=chain,
        )

    def add_coin(self, candidate: CoinCandidate) -> None:
        """Persist a confirmed coin and update the live catalog."""
        with self._catalog_lock:
            if candidate.symbol in self.cryptos:
                raise CoinCreationError(f"{candidate.symbol} is already known by the bot.")
            updated = {**self.cryptos, candidate.symbol: candidate.record()}
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".cryptos-", suffix=".json", dir=self.crypto_path.parent
            )
            try:
                with os.fdopen(file_descriptor, 'w', encoding='utf-8') as output:
                    json.dump(updated, output, indent=4)
                os.replace(temporary_path, self.crypto_path)
            finally:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
            self.cryptos.clear()
            self.cryptos.update(updated)
