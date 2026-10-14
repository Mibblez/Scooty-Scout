"""Check the boundary between shared behavior and Telegram delivery."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext
from telegram_adapter import TelegramAdapter

TELEGRAM_CONTEXT = CommandContext(Backend.TELEGRAM, "7", "-1001", "Ada Lovelace")


class FakeTelegramBot:
    def __init__(self):
        self.handlers = {}
        self.reply_to = Mock()
        self.send_message = Mock()

    def message_handler(self, *, commands):
        def register(handler):
            for command in commands:
                self.handlers[command] = handler
            return handler

        return register


@pytest.fixture
def telegram_application():
    return SimpleNamespace(
        coins=Mock(return_value="Known coins:\nBTC"),
        price=Mock(return_value="Price response"),
        price_notify=Mock(return_value="Notification response"),
        check_notifications=Mock(return_value="TST at $12.0\n"),
        price_alerts=SimpleNamespace(has_user=Mock(return_value=True)),
    )


@pytest.fixture
def telegram_bot(telegram_application):
    bot = FakeTelegramBot()
    TelegramAdapter(bot, telegram_application).register()
    return bot


@pytest.fixture
def message():
    return SimpleNamespace(
        text="/price btc",
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=7, first_name="Ada", last_name="Lovelace"),
    )


def test_coins_logic_accepts_a_discord_context():
    application = BotApplication({"BTC": {}, "ETH": {}})
    context = CommandContext(Backend.DISCORD, "7", "99", "Ada")

    assert application.coins(context) == "Known coins:\nBTC ; ETH"


def test_telegram_coins_translates_context_and_replies(telegram_bot, telegram_application, message):
    telegram_bot.handlers["coins"](message)

    telegram_application.coins.assert_called_once_with(TELEGRAM_CONTEXT)
    telegram_bot.reply_to.assert_called_once_with(message, "Known coins:\nBTC")


@pytest.mark.parametrize("command", ["check_notifications", "cnot"], ids=["full-command", "alias"])
def test_telegram_check_notifications_uses_shared_logic(telegram_bot, telegram_application, message, command):
    message.text = f"/{command}"

    telegram_bot.handlers[command](message)

    telegram_application.check_notifications.assert_called_once_with(TELEGRAM_CONTEXT)
    telegram_bot.reply_to.assert_called_once_with(message, "TST at $12.0\n")


@pytest.mark.parametrize(
    ("command_text", "expected_symbol"),
    [("/price btc", "btc"), ("/price", ""), ("/price BTC ETH", "")],
    ids=["valid-symbol", "missing-symbol", "too-many-arguments"],
)
def test_telegram_price_translates_arguments(
    telegram_bot, telegram_application, message, command_text, expected_symbol
):
    message.text = command_text

    telegram_bot.handlers["price"](message)

    telegram_application.price.assert_called_once_with(TELEGRAM_CONTEXT, expected_symbol)
    telegram_bot.send_message.assert_called_once_with(message.chat.id, "Price response")


def test_telegram_price_notify_requires_start(telegram_bot, telegram_application, message):
    telegram_application.price_alerts.has_user.return_value = False
    message.text = "/price_notify btc $12"

    telegram_bot.handlers["price_notify"](message)

    telegram_application.price_notify.assert_not_called()
    reply = telegram_bot.reply_to.call_args.args[1]
    assert "/start" in reply


def test_telegram_price_notify_alias_uses_shared_logic(telegram_bot, telegram_application, message):
    message.text = "/pnot btc $12"

    telegram_bot.handlers["pnot"](message)

    telegram_application.price_notify.assert_called_once_with(TELEGRAM_CONTEXT, "btc", "$12")
    telegram_bot.reply_to.assert_called_once_with(message, "Notification response")
