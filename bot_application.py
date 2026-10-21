"""Provide shared command logic for platform adapters."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from bot_utilities import cmc_id_map, get_coin_data, get_coin_info, unknown_coin, usage_error
from command_context import CommandContext
from ethereum_gas import GasPrices, get_ethereum_gas
from group_notifications import GroupNotificationError, GroupNotifications
from json_storage import write_json_atomically
from media_commands import IMAGE_EXTENSIONS, MediaCommand, MediaCommandError, MediaCommands
from price_alerts import PriceAlerts, PriceAlertError
from twitter_videos import download_twitter_video
from wen import WenReply, get_wen_reply

logger = logging.getLogger("scooty_scout")


class CoinCreationError(ValueError):
    """A coin lookup or creation request failed."""


class CoinInfoError(ValueError):
    """The bot cannot find or display the requested coin."""


class CoinUpdateError(ValueError):
    """A metadata change failed validation."""


@dataclass(frozen=True)
class CoinUpdate:
    symbol: str
    field: str
    value: str
    previous_value: Any

    def preview(self) -> str:
        previous = self.previous_value if self.previous_value not in (None, "") else "(not set)"
        return f"Update {self.symbol}: {self.field}\n\nCurrent: {previous}\nNew: {self.value}"


@dataclass(frozen=True)
class CoinInfo:
    symbol: str
    name: str
    fields: list[tuple[str, str]]
    links: list[tuple[str, str]]

    @property
    def title(self) -> str:
        return f"{self.name} ({self.symbol})" if self.name != self.symbol else self.symbol

    def as_text(self) -> str:
        lines = [self.title]
        if self.fields:
            lines.append("")
            lines.extend(f"{label}: {value}" for label, value in self.fields)
        if self.links:
            lines.append("")
            lines.extend(f"{label}: {url}" for label, url in self.links)
        if not self.fields and not self.links:
            lines.extend(["", "No additional information available."])
        return "\n".join(lines)


@dataclass(frozen=True)
class CoinCandidate:
    symbol: str
    name: str
    cmc_id: str
    website: str
    contract_id: str | None
    chain: str | None
    slug: str | None = None

    def preview(self) -> str:
        return (
            f"-- {self.contract_id or self.name} --\n"
            f"Name: {self.name}\nSymbol: {self.symbol}\n"
            f"Chain: {self.chain}"
        )

    def record(self) -> dict[str, Any]:
        record = {
            "INFO": {
                "contract_id": self.contract_id,
                "chain": self.chain,
                "website": self.website,
            },
            "cmc_id": self.cmc_id,
            "cmc_name": self.name,
        }
        if self.slug:
            record["cmc_slug"] = self.slug
        return record


class BotApplication:
    def __init__(
        self,
        cryptos: Mapping[str, Any],
        cmc_api_key: str | None = None,
        crypto_path: str | Path = "cryptos.json",
        notification_path: str | Path | None = None,
        etherscan_api_key: str | None = None,
        media_path: str | Path | None = None,
    ) -> None:
        # Keep the original dictionary so services share catalog updates.
        self.cryptos = cryptos if isinstance(cryptos, dict) else dict(cryptos)
        self.cmc_api_key = cmc_api_key
        self.etherscan_api_key = etherscan_api_key
        self.crypto_path = Path(crypto_path)
        self._catalog_lock = Lock()
        self.price_alerts = PriceAlerts(self.cryptos, cmc_api_key, notification_path) if notification_path else None
        self.group_notifications = GroupNotifications(notification_path) if notification_path else None
        self.media_commands = MediaCommands(media_path) if media_path is not None else None

    def coins(self, _context: CommandContext) -> str:
        return "Known coins:\n" + " ; ".join(self.cryptos)

    def prepare_media_command(self, name: str, filename: str, group: str, size: int) -> MediaCommand:
        if self.media_commands is None:
            raise MediaCommandError("Custom media commands are not configured.")
        if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
            raise MediaCommandError("Attach a PNG, JPEG, GIF, or WebP image.")
        return self.media_commands.prepare(name, filename, group, size)

    def prepare_twitter_video_command(self, name: str, group: str = "user_commands") -> MediaCommand:
        if self.media_commands is None:
            raise MediaCommandError("Custom media commands are not configured.")
        return self.media_commands.prepare(name, "video.mp4", group)

    def add_twitter_video_command(self, command: MediaCommand, url: str) -> None:
        self.add_media_command(command, download_twitter_video(url))

    def add_media_command(self, command: MediaCommand, content: bytes) -> None:
        if self.media_commands is None:
            raise MediaCommandError("Custom media commands are not configured.")
        self.media_commands.add(command, content)

    def list_commands(self, _context: CommandContext, group: str | None = None) -> str:
        if self.media_commands is None:
            raise MediaCommandError("Custom media commands are not configured.")
        return self.media_commands.list_commands(group)

    def wen(self, _context: CommandContext, thing: str) -> WenReply | None:
        return get_wen_reply(thing)

    def info(self, _context: CommandContext, symbol: str) -> CoinInfo:
        symbol = symbol.strip().upper()
        if not symbol:
            raise CoinInfoError(usage_error("/info COIN_SYMBOL"))
        if symbol not in self.cryptos:
            raise CoinInfoError(unknown_coin(symbol, self.cryptos))

        coin = self.cryptos[symbol]
        metadata = coin.get("INFO") or {}
        labels = {"chain": "Network", "website": "Website", "contract_id": "Contract address"}
        ordered_keys = list(labels) + [key for key in metadata if key not in labels]
        fields = []
        for key in ordered_keys:
            value = metadata.get(key)
            if value is not None and value != "":
                fields.append((labels.get(key, key.replace("_", " ").title()), str(value)))

        links = []
        chain = metadata.get("chain")
        contract_id = metadata.get("contract_id")
        if chain in ("BSC", "BNB BEP20") and contract_id:
            links.append(("BscScan", f"https://www.bscscan.com/address/{contract_id}"))
            links.append(("DEXTools", f"https://www.dextools.io/app/bsc/pair-explorer/{contract_id}"))
        elif chain:
            slug = coin.get("cmc_slug") or (coin.get("cmc_name") or "").lower().replace(" ", "-")
            if slug:
                links.append(("CoinMarketCap", f"https://coinmarketcap.com/currencies/{slug}/"))
        return CoinInfo(symbol, coin.get("cmc_name") or symbol, fields, links)

    def price(self, _context: CommandContext, symbol: str) -> str:
        symbol = symbol.strip().upper()
        if not symbol:
            return usage_error("/price COIN_SYMBOL")
        if symbol not in self.cryptos:
            return unknown_coin(symbol, self.cryptos)

        unavailable = "Could not get the latest price. Try again later."
        if not self.cmc_api_key:
            return unavailable
        try:
            coin_id = str(self.cryptos[symbol]["cmc_id"])
            coin_data = get_coin_data(coin_id, self.cmc_api_key)
            if coin_data is None:
                return unavailable
            quote = coin_data["data"][coin_id]["quote"]["USD"]
            latest_price = f"{quote['price']:.10f}"
            percent_change_24h = float(f"{quote['percent_change_24h']:.2f}")
        except KeyError, TypeError, ValueError:
            logger.warning("CoinMarketCap returned an invalid quote for %s", symbol)
            return unavailable

        movement_direction = "⬆️" if percent_change_24h > 0.0 else "⬇️"
        return f"{symbol} Price: ${latest_price}\n{movement_direction} {percent_change_24h}% (24H)"

    def ethgas(self, _context: CommandContext) -> GasPrices:
        return get_ethereum_gas(self.etherscan_api_key)

    def price_notify(self, context: CommandContext, symbol: str, target: str | float) -> str:
        if self.price_alerts is None:
            raise PriceAlertError("Price notifications are not configured.")
        return self.price_alerts.set_notification(context, symbol, target)

    def check_notifications(self, context: CommandContext) -> str:
        if self.price_alerts is None:
            raise PriceAlertError("Price notifications are not configured.")
        notifications = self.price_alerts.list_notifications(context)
        if not notifications:
            return "No notifications set"
        return "".join(f"{coin} at ${target}\n" for coin, target in notifications)

    def delete_notification(self, context: CommandContext, symbol: str) -> str:
        if self.price_alerts is None:
            raise PriceAlertError("Price notifications are not configured.")
        return self.price_alerts.delete_notification(context, symbol)

    def notify_me(self, context: CommandContext) -> str:
        if self.group_notifications is None:
            raise GroupNotificationError("Group notifications are not configured.")
        return self.group_notifications.notify_me(context)

    def dont_notify_me(self, context: CommandContext) -> str:
        if self.group_notifications is None:
            raise GroupNotificationError("Group notifications are not configured.")
        return self.group_notifications.dont_notify_me(context)

    def group_subscribers(self, context: CommandContext) -> tuple[str, ...]:
        if self.group_notifications is None:
            raise GroupNotificationError("Group notifications are not configured.")
        return self.group_notifications.subscribers(context.conversation_id)

    def prepare_new_coin(self, identifier: str) -> CoinCandidate:
        """Look up a coin for review before saving."""
        identifier = identifier.strip()
        if not identifier:
            raise CoinCreationError("Provide a contract address or coin symbol.")
        if not self.cmc_api_key:
            raise CoinCreationError("CoinMarketCap API key is not configured.")

        if identifier.startswith("0x"):
            response = get_coin_info(identifier, self.cmc_api_key)
        else:
            mapping = cmc_id_map(identifier.upper(), self.cmc_api_key)
            if mapping is None:
                raise CoinCreationError("Could not reach CoinMarketCap. Try again later.")
            error = mapping.get("status", {}).get("error_message")
            if error:
                raise CoinCreationError(f"Could not add coin: {error}")
            matches = mapping.get("data") or []
            if len(matches) != 1:
                raise CoinCreationError(
                    f"Found {len(matches)} cryptocurrencies matching {identifier}. "
                    "Use a contract address to identify one coin."
                )
            response = get_coin_info(None, self.cmc_api_key, id=int(matches[0]["id"]))

        if response is None:
            raise CoinCreationError("Could not reach CoinMarketCap. Try again later.")
        error = response.get("status", {}).get("error_message")
        if error:
            raise CoinCreationError(f"Could not add coin: {error}")
        data = response.get("data") or {}
        if len(data) != 1:
            raise CoinCreationError("CoinMarketCap did not return one coin. Use a contract address.")

        cmc_id, coin = next(iter(data.items()))
        symbol = coin["symbol"].upper()
        if symbol in self.cryptos:
            raise CoinCreationError(f"Cannot add coin. {symbol} is already known by the bot.")
        platform = coin.get("platform")
        chain = platform["symbol"] if platform else None
        contract_id = platform["token_address"] if platform else None
        if chain == "ETH":
            chain = "ETH ERC-20"
        elif chain == "BNB":
            chain = "BNB BEP20"
        websites = coin.get("urls", {}).get("website") or []
        return CoinCandidate(
            symbol=symbol,
            name=coin["name"],
            cmc_id=str(cmc_id),
            website=websites[0] if websites else "",
            contract_id=contract_id,
            chain=chain,
            slug=coin.get("slug"),
        )

    def add_coin(self, candidate: CoinCandidate) -> None:
        """Save a confirmed coin and update the shared catalog."""
        with self._catalog_lock:
            if candidate.symbol in self.cryptos:
                raise CoinCreationError(f"{candidate.symbol} is already known by the bot.")
            updated = {**self.cryptos, candidate.symbol: candidate.record()}
            self._save_catalog(updated)

    def prepare_coin_update(self, symbol: str, field: str, value: str) -> CoinUpdate:
        """Prepare a metadata change for confirmation."""
        symbol = symbol.strip().upper()
        field = field.strip()
        value = value.strip()
        if not symbol:
            raise CoinUpdateError(usage_error("/update_crypto COIN_SYMBOL"))
        if symbol not in self.cryptos:
            raise CoinUpdateError(f"Cannot update coin: unknown coin {symbol}")
        if not field:
            raise CoinUpdateError("Provide a metadata field, such as website, chain, or contract_id.")
        if not value:
            raise CoinUpdateError("Provide a non-empty value for the metadata field.")
        metadata = self.cryptos[symbol].get("INFO") or {}
        return CoinUpdate(symbol, field, value, metadata.get(field))

    def update_coin(self, change: CoinUpdate) -> None:
        """Save a confirmed change, rejecting a stale preview."""
        with self._catalog_lock:
            current = self.prepare_coin_update(change.symbol, change.field, change.value)
            if current.previous_value != change.previous_value:
                raise CoinUpdateError("This field changed after your preview. Run /update_crypto again to review it.")
            coin = self.cryptos[current.symbol]
            metadata = {**(coin.get("INFO") or {}), current.field: current.value}
            updated_coin = {**coin, "INFO": metadata}
            self._save_catalog({**self.cryptos, current.symbol: updated_coin})

    def _save_catalog(self, updated: dict[str, Any]) -> None:
        """Save before updating shared data; the caller holds the catalog lock."""
        write_json_atomically(self.crypto_path, updated)
        self.cryptos.clear()
        self.cryptos.update(updated)
