"""Manage Telegram group subscriptions and deliver price alerts."""

import functools
import logging
import sqlite3
import time
from contextlib import closing

import globals
from price_alerts import PriceAlerts

logger = logging.getLogger("scooty_scout")


def initialize_db():
    with closing(sqlite3.connect("notifications.db")) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS price_notifications("
            "notification_id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, user_id INTEGER, "
            "notify_at FLOAT, direction CHAR, FOREIGN KEY(user_id) REFERENCES users(user_id))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS at_everyone_notifications(" "group_chat_id INTEGER PRIMARY KEY, to_notify TEXT)"
        )


def uses_notification_db(func):
    """Pass a database cursor to a handler and commit successful changes."""

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        with closing(sqlite3.connect("notifications.db")) as connection, connection:
            func(connection.cursor(), *args, **kwargs)

    return wrapped


@globals.bot.message_handler(commands=["notify_me"])
@uses_notification_db
def at_everyone_opt_in(cursor, message):
    if message.chat.type == "private":
        return

    chat_id = message.chat.id
    user_id = str(message.from_user.id)

    cursor.execute("SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id = ?", (chat_id,))
    if (result := cursor.fetchone()) is not None:
        entries = result[0].split(";") if result[0] else []

        if any(entry.rsplit("|", 1)[-1] == user_id for entry in entries):
            globals.bot.reply_to(message, "You're already receiving @everyone notifications")
            return

        entries.append(f"{message.from_user.first_name}|{user_id}")
        cursor.execute(
            "UPDATE at_everyone_notifications SET to_notify = ? WHERE group_chat_id = ?",
            (";".join(entries), chat_id),
        )
    else:
        cursor.execute(
            "INSERT INTO at_everyone_notifications(group_chat_id, to_notify) VALUES (?, ?)",
            (chat_id, f"{message.from_user.first_name}|{user_id}"),
        )

    globals.bot.reply_to(message, "You will now be notified when someone uses the /everyone command")


@globals.bot.message_handler(commands=["dont_notify_me"])
@uses_notification_db
def at_everyone_opt_out(cursor, message):
    if message.chat.type == "private":
        return

    chat_id = message.chat.id
    user_id = str(message.from_user.id)

    cursor.execute("SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id = ?", (chat_id,))
    if (result := cursor.fetchone()) is not None:
        entries = result[0].split(";")
        remaining_entries = [entry for entry in entries if entry.rsplit("|", 1)[-1] != user_id]
        cursor.execute(
            "UPDATE at_everyone_notifications SET to_notify = ? WHERE group_chat_id = ?",
            (";".join(remaining_entries), chat_id),
        )

    globals.bot.reply_to(message, "You won't be notified when someone uses the /everyone command")


def check_price_notifications(alerts: PriceAlerts):
    while True:
        try:
            for notification in alerts.due_notifications():
                try:
                    if not alerts.is_pending(notification.notification_id):
                        continue
                    globals.bot.send_message(notification.user_id, notification.message())
                    alerts.acknowledge(notification.notification_id)
                except Exception:
                    logger.exception(
                        "Telegram price notification %s failed; retaining it for retry", notification.notification_id
                    )
        except Exception:
            logger.exception("Telegram price notification check failed")
        time.sleep(900)
