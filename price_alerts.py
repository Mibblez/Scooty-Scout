"""Persistent price alert rules shared by chat-platform adapters."""

import logging
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot_utilities import get_coin_data, unknown_coin
from command_context import CommandContext

logger = logging.getLogger("scooty_scout")


class PriceAlertError(ValueError):
    """A price alert could not be configured."""


@dataclass(frozen=True)
class TriggeredPriceAlert:
    notification_id: int
    user_id: int
    coin: str
    target: float
    direction: str
    current_price: float

    def message(self) -> str:
        if self.direction == "+":
            return "HEY FELLOW 🦍!\n" f"{self.coin} has risen above ${self.target} and is at ${self.current_price}."
        return "HEY 🌈🐻!\n" f"{self.coin} has fallen below ${self.target} and is at ${self.current_price}."


class PriceAlerts:
    def __init__(self, cryptos: dict[str, Any], cmc_api_key: str | None, db_path: str | Path) -> None:
        self.cryptos = cryptos
        self.cmc_api_key = cmc_api_key
        self.db_path = Path(db_path)
        # Preserve the Telegram schema so its existing alerts remain usable.
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS price_notifications("
                "notification_id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, user_id INTEGER, "
                "notify_at FLOAT, direction CHAR, FOREIGN KEY(user_id) REFERENCES users(user_id))"
            )

    def has_user(self, user_id: str) -> bool:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is not None

    def list_notifications(self, context: CommandContext) -> list[tuple[str, float]]:
        """Return only the caller's saved alerts, without fetching market data."""
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute(
                "SELECT coin, notify_at FROM price_notifications WHERE user_id = ? ORDER BY coin",
                (context.user_id,),
            ).fetchall()

    @staticmethod
    def _price(data: Any, coin_id: str) -> float:
        price = float(data["data"][coin_id]["quote"]["USD"]["price"])
        if not math.isfinite(price) or price < 0:
            raise ValueError("Invalid market price")
        return price

    def set_notification(self, context: CommandContext, symbol: str, target: str | float) -> str:
        symbol = symbol.strip().upper()
        if symbol not in self.cryptos:
            raise PriceAlertError(unknown_coin(symbol, self.cryptos))
        try:
            target_price = float(target.strip("$") if isinstance(target, str) else target)
            if not math.isfinite(target_price) or target_price <= 0:
                raise ValueError("Invalid target price")
        except (TypeError, ValueError) as error:
            raise PriceAlertError("Price target must be a positive, finite number.") from error

        try:
            if not self.cmc_api_key:
                raise ValueError("Missing market data configuration")
            coin_id = str(self.cryptos[symbol]["cmc_id"])
            latest_price = self._price(get_coin_data(coin_id, self.cmc_api_key), coin_id)
        except (KeyError, TypeError, ValueError) as error:
            raise PriceAlertError("Could not get the latest price. Try again later.") from error
        direction = "+" if latest_price < target_price else "-"

        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "INSERT INTO users(user_id, name) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name",
                (context.user_id, context.display_name),
            )
            # A new ID prevents completion of an old alert from deleting its replacement.
            connection.execute(
                "DELETE FROM price_notifications WHERE user_id = ? AND coin = ?",
                (context.user_id, symbol),
            )
            connection.execute(
                "INSERT INTO price_notifications(coin, user_id, notify_at, direction) VALUES (?, ?, ?, ?)",
                (symbol, context.user_id, target_price, direction),
            )
        return f"Created notification for {symbol} at ${target_price}"

    def due_notifications(self) -> list[TriggeredPriceAlert]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            notifications = connection.execute(
                "SELECT notification_id, coin, user_id, notify_at, direction FROM price_notifications"
            ).fetchall()
        if not notifications:
            return []

        coin_ids = {
            coin: str(self.cryptos[coin]["cmc_id"]) for _, coin, _, _, _ in notifications if coin in self.cryptos
        }
        if not coin_ids or not self.cmc_api_key:
            return []
        try:
            data = get_coin_data(",".join(dict.fromkeys(coin_ids.values())), self.cmc_api_key)
        except TypeError, ValueError:
            logger.warning("Price notification check skipped because market data is invalid")
            return []
        if data is None:
            logger.warning("Price notification check skipped because market data is unavailable")
            return []

        prices = {}
        for coin, coin_id in coin_ids.items():
            try:
                prices[coin] = self._price(data, coin_id)
            except KeyError, TypeError, ValueError:
                logger.warning("Price notification check skipped for %s because its quote is invalid", coin)

        due = []
        for notification_id, coin, user_id, target, direction in notifications:
            if coin not in prices:
                continue
            price = prices[coin]
            if (direction == "+" and price > target) or (direction == "-" and price < target):
                due.append(TriggeredPriceAlert(notification_id, user_id, coin, target, direction, price))
        return due

    def acknowledge(self, notification_id: int) -> None:
        """Remove an alert only after its platform has delivered it successfully."""
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DELETE FROM price_notifications WHERE notification_id = ?", (notification_id,))
