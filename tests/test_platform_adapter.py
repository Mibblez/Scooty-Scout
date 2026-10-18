"""Check the boundary between shared behavior and Telegram delivery."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend_config import Backend
from bot_application import CoinInfo
from command_context import CommandContext
from ethereum_gas import GasPriceError
from telegram_adapter import TelegramAdapter
from wen import WenReply

TELEGRAM_CONTEXT = CommandContext(Backend.TELEGRAM, "7", "-1001", "Ada Lovelace")


class FakeTelegramBot:
    def __init__(self):
        self.handlers = {}
        self.reply_to = Mock()
        self.send_message = Mock()
        self.send_audio = Mock()

    def message_handler(self, *, commands):
        def register(handler):
            for command in commands:
                self.handlers[command] = handler
            return handler

        return register


@pytest.fixture
def telegram_application(gas_prices):
    return SimpleNamespace(
        coins=Mock(return_value="Known coins:\nBTC"),
        info=Mock(return_value=CoinInfo("TST", "Test Coin", [("Website", "https://example.com")], [])),
        price=Mock(return_value="Price response"),
        ethgas=Mock(return_value=gas_prices),
        wen=Mock(return_value=WenReply("HODL")),
        price_notify=Mock(return_value="Notification response"),
        check_notifications=Mock(return_value="TST at $12.0\n"),
        delete_notification=Mock(return_value="Notification for TST deleted"),
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


def test_telegram_coins_translates_context_and_replies(telegram_bot, telegram_application, message):
    telegram_bot.handlers["coins"](message)

    telegram_application.coins.assert_called_once_with(TELEGRAM_CONTEXT)
    telegram_bot.reply_to.assert_called_once_with(message, "Known coins:\nBTC")


@pytest.mark.parametrize(
    ("command_text", "expected_symbol"),
    [("/info tst", "tst"), ("/info", ""), ("/info BTC ETH", "")],
    ids=["valid-symbol", "missing-symbol", "too-many-arguments"],
)
def test_telegram_info_translates_arguments(telegram_bot, telegram_application, message, command_text, expected_symbol):
    message.text = command_text

    telegram_bot.handlers["info"](message)

    telegram_application.info.assert_called_once_with(TELEGRAM_CONTEXT, expected_symbol)
    telegram_bot.send_message.assert_called_once_with(
        message.chat.id, "Test Coin (TST)\n\nWebsite: https://example.com"
    )


def test_telegram_ethgas_uses_shared_lookup(telegram_bot, telegram_application, message, gas_prices):
    message.text = "/ethgas"

    telegram_bot.handlers["ethgas"](message)

    telegram_application.ethgas.assert_called_once_with(TELEGRAM_CONTEXT)
    telegram_bot.send_message.assert_called_once_with(message.chat.id, gas_prices.as_text())


def test_telegram_ethgas_explains_lookup_failure(telegram_bot, telegram_application, message):
    message.text = "/ethgas"
    telegram_application.ethgas.side_effect = GasPriceError("Could not get Ethereum gas prices.")

    telegram_bot.handlers["ethgas"](message)

    telegram_bot.send_message.assert_called_once_with(message.chat.id, "Could not get Ethereum gas prices.")


@pytest.mark.parametrize(
    ("command", "thing"), [("wen", "MOON"), ("WEN", "lambo")], ids=["uppercase-topic", "uppercase-command"]
)
def test_telegram_wen_translates_arguments(telegram_bot, telegram_application, message, command, thing):
    message.text = f"/{command} {thing}"

    telegram_bot.handlers[command](message)

    telegram_application.wen.assert_called_once_with(TELEGRAM_CONTEXT, thing)
    telegram_bot.reply_to.assert_called_once_with(message, "HODL")
    telegram_bot.send_audio.assert_not_called()


@pytest.mark.parametrize("text", ["/wen", "/wen moon lambo"], ids=["missing-topic", "too-many-arguments"])
def test_telegram_wen_ignores_invalid_arguments(telegram_bot, telegram_application, message, text):
    message.text = text

    telegram_bot.handlers["wen"](message)

    telegram_application.wen.assert_not_called()
    telegram_bot.reply_to.assert_not_called()


def test_telegram_wen_sends_optional_audio(telegram_bot, telegram_application, message, moon_audio):
    message.text = "/wen moon"
    telegram_application.wen.return_value = WenReply("HODL", moon_audio)

    telegram_bot.handlers["wen"](message)

    telegram_bot.reply_to.assert_called_once_with(message, "HODL")
    audio = telegram_bot.send_audio.call_args.kwargs["audio"]
    assert audio.name == str(moon_audio)
    assert audio.closed


@pytest.mark.parametrize("command", ["check_notifications", "cnot"], ids=["full-command", "alias"])
def test_telegram_check_notifications_uses_shared_logic(telegram_bot, telegram_application, message, command):
    message.text = f"/{command}"

    telegram_bot.handlers[command](message)

    telegram_application.check_notifications.assert_called_once_with(TELEGRAM_CONTEXT)
    telegram_bot.reply_to.assert_called_once_with(message, "TST at $12.0\n")


@pytest.mark.parametrize("command", ["delete_notification", "dnot"], ids=["full-command", "alias"])
def test_telegram_delete_notification_uses_shared_logic(telegram_bot, telegram_application, message, command):
    message.text = f"/{command} tst"

    telegram_bot.handlers[command](message)

    telegram_application.delete_notification.assert_called_once_with(TELEGRAM_CONTEXT, "tst")
    telegram_bot.reply_to.assert_called_once_with(message, "Notification for TST deleted")


@pytest.mark.parametrize(
    "command_text",
    ["/delete_notification", "/delete_notification BTC ETH"],
    ids=["missing-symbol", "too-many-arguments"],
)
def test_telegram_delete_notification_validates_arguments(telegram_bot, telegram_application, message, command_text):
    message.text = command_text

    telegram_bot.handlers["delete_notification"](message)

    telegram_application.delete_notification.assert_not_called()
    telegram_bot.send_message.assert_called_once_with(message.chat.id, "Usage\n/delete_notification COIN_SYMBOL")


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
