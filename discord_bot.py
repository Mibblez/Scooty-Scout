"""Load Discord configuration and start its adapter."""

import json
import os
from ast import literal_eval
from pathlib import Path

from bot_application import BotApplication
from discord_adapter import DiscordAdapter
from logging_setup import configure_logging


def _admin_ids(value: str | None) -> set[int]:
    try:
        parsed = literal_eval(value or "")
    except (SyntaxError, ValueError) as error:
        raise ValueError("DISCORD_ADMIN_IDS must be a list of positive user IDs") from error
    if (
        not isinstance(parsed, list)
        or not parsed
        or any(type(user_id) is not int or user_id <= 0 for user_id in parsed)
    ):
        raise ValueError("DISCORD_ADMIN_IDS must be a nonempty list of positive user IDs")
    return set(parsed)


def run() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    cmc_key = os.getenv("COINMARKETCAP_API_KEY")
    if not token or not cmc_key:
        raise SystemExit("DISCORD_BOT_TOKEN and COINMARKETCAP_API_KEY are required")
    try:
        admin_ids = _admin_ids(os.getenv("DISCORD_ADMIN_IDS"))
        guild_value = os.getenv("DISCORD_GUILD_ID")
        guild_id = int(guild_value) if guild_value else None
        if guild_id is not None and guild_id <= 0:
            raise ValueError("DISCORD_GUILD_ID must be positive")
    except ValueError as error:
        raise SystemExit(str(error)) from error

    crypto_path = Path("cryptos.json")
    if not crypto_path.exists():
        raise SystemExit("cryptos.json not found; create it from cryptos_example.json")
    with crypto_path.open(encoding="utf-8") as source:
        cryptos = json.load(source)

    configure_logging()
    application = BotApplication(
        cryptos,
        cmc_key,
        crypto_path,
        notification_path="discord_notifications.db",
        etherscan_api_key=os.getenv("ETHERSCAN_API_KEY"),
        media_path="media/discord",
    )
    DiscordAdapter(application, admin_ids, guild_id).run(token)
