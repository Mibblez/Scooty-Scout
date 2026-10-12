"""Check the boundary between shared behavior and Telegram delivery."""

from types import SimpleNamespace

from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext
from telegram_adapter import TelegramAdapter


def test_coins_logic_accepts_a_discord_context() -> None:
    application = BotApplication({"BTC": {}, "ETH": {}})
    context = CommandContext(Backend.DISCORD, "7", "99", "Ada")

    assert application.coins(context) == "Known coins:\nBTC ; ETH"


def test_telegram_adapter_translates_coins_and_replies() -> None:
    class RecordingApplication(BotApplication):
        def __init__(self) -> None:
            super().__init__({"BTC": {}})
            self.context = None

        def coins(self, context):
            self.context = context
            return super().coins(context)

    class FakeBot:
        def __init__(self) -> None:
            self.handler = None
            self.replies = []

        def message_handler(self, *, commands):
            assert commands == ['coins']

            def register(handler):
                self.handler = handler
                return handler

            return register

        def reply_to(self, message, text):
            self.replies.append((message, text))

    bot = FakeBot()
    application = RecordingApplication()
    TelegramAdapter(bot, application).register()
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=7, first_name="Ada", last_name="Lovelace"),
    )

    bot.handler(message)

    assert bot.replies == [(message, "Known coins:\nBTC")]
    assert application.context == CommandContext(
        Backend.TELEGRAM, "7", "-1001", "Ada Lovelace"
    )
