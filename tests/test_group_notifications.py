"""Group subscription persistence and isolation without platform APIs."""

from dataclasses import replace

import pytest

from backend_config import Backend
from bot_application import BotApplication


@pytest.fixture
def group_application(tmp_path):
    return BotApplication({}, notification_path=tmp_path / "discord_notifications.db")


def test_group_preferences_persist_and_repeated_commands_are_safe(group_application, discord_context):
    assert group_application.notify_me(discord_context) == "You're now subscribed to /everyone notifications here."
    assert group_application.notify_me(discord_context) == "You're already subscribed to /everyone notifications here."

    path = group_application.group_notifications.db_path
    reopened = BotApplication({}, notification_path=path)
    assert reopened.group_notifications.subscribers(discord_context.conversation_id) == (discord_context.user_id,)
    assert reopened.dont_notify_me(discord_context) == "You won't receive /everyone notifications here."
    assert reopened.dont_notify_me(discord_context) == "You won't receive /everyone notifications here."

    reopened = BotApplication({}, notification_path=path)
    assert reopened.group_notifications.subscribers(discord_context.conversation_id) == ()


def test_opt_out_preserves_other_users_and_conversations(group_application, discord_context):
    other_user = replace(discord_context, user_id="18")
    other_channel = replace(discord_context, conversation_id="456")
    for context in (discord_context, other_user, other_channel):
        group_application.notify_me(context)

    group_application.dont_notify_me(discord_context)

    subscriptions = group_application.group_notifications
    assert subscriptions.subscribers(discord_context.conversation_id) == (other_user.user_id,)
    assert subscriptions.subscribers(other_channel.conversation_id) == (discord_context.user_id,)


def test_discord_group_preferences_are_separate_from_telegram(group_application, discord_context, tmp_path):
    telegram = BotApplication({}, notification_path=tmp_path / "notifications.db")
    telegram_context = replace(discord_context, backend=Backend.TELEGRAM)
    group_application.notify_me(discord_context)

    assert telegram.group_notifications.subscribers(telegram_context.conversation_id) == ()
    telegram.notify_me(telegram_context)
    telegram.dont_notify_me(telegram_context)

    assert group_application.group_notifications.subscribers(discord_context.conversation_id) == (
        discord_context.user_id,
    )
