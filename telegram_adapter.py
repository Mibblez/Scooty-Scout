"""Register Telegram commands and translate their inputs and responses."""

from backend_config import Backend
from bot_application import BotApplication
from command_context import CommandContext


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
        @self.bot.message_handler(commands=['coins'])
        def coins(message):
            context = context_from_message(message)
            self.bot.reply_to(message, self.application.coins(context))
