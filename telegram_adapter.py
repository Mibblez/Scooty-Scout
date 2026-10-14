"""Register Telegram commands and translate their inputs and responses."""

from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext
from bot_utilities import usage_error
from price_alerts import PriceAlertError


def context_from_message(message) -> CommandContext:
    user = message.from_user
    return CommandContext(
        backend=Backend.TELEGRAM,
        user_id=str(user.id),
        conversation_id=str(message.chat.id),
        display_name=f"{user.first_name} {user.last_name}",
    )


class TelegramAdapter:
    def __init__(self, bot, application: BotApplication) -> None:
        self.bot = bot
        self.application = application

    def register(self) -> None:
        @self.bot.message_handler(commands=["coins"])
        def coins(message):
            context = context_from_message(message)
            self.bot.reply_to(message, self.application.coins(context))

        @self.bot.message_handler(commands=["price"])
        def price(message):
            arguments = message.text.split()
            symbol = arguments[1] if len(arguments) == 2 else ""
            response = self.application.price(context_from_message(message), symbol)
            self.bot.send_message(message.chat.id, response)

        @self.bot.message_handler(commands=["price_notify", "pnot"])
        def price_notify(message):
            arguments = message.text.split()
            if len(arguments) != 3:
                self.bot.send_message(message.chat.id, usage_error("/price_notify COIN_SYMBOL PRICE_TARGET"))
                return
            context = context_from_message(message)
            alerts = self.application.price_alerts
            if alerts is not None and not alerts.has_user(context.user_id):
                self.bot.reply_to(message, "Cannot set price notification. You must DM the bot /start first.")
                return
            try:
                response = self.application.price_notify(context, arguments[1], arguments[2])
            except PriceAlertError as error:
                response = str(error)
            self.bot.reply_to(message, response)

        @self.bot.message_handler(commands=["check_notifications", "cnot"])
        def check_notifications(message):
            try:
                response = self.application.check_notifications(context_from_message(message))
            except PriceAlertError as error:
                response = str(error)
            self.bot.reply_to(message, response)
