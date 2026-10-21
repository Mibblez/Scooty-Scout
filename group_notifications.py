"""Store group subscriptions separately for each conversation."""

import sqlite3
from contextlib import closing
from pathlib import Path

from command_context import CommandContext


class GroupNotificationError(ValueError):
    """The bot cannot access group notification settings."""


class GroupNotifications:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS group_notification_subscriptions("
                "conversation_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                "PRIMARY KEY(conversation_id, user_id))"
            )

    def notify_me(self, context: CommandContext) -> str:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO group_notification_subscriptions(conversation_id, user_id) VALUES (?, ?) "
                "ON CONFLICT(conversation_id, user_id) DO NOTHING",
                (context.conversation_id, context.user_id),
            )
            if cursor.rowcount == 0:
                return "You're already subscribed to /everyone notifications here."
        return "You're now subscribed to /everyone notifications here."

    def dont_notify_me(self, context: CommandContext) -> str:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "DELETE FROM group_notification_subscriptions WHERE conversation_id = ? AND user_id = ?",
                (context.conversation_id, context.user_id),
            )
        return "You won't receive /everyone notifications here."

    def subscribers(self, conversation_id: str) -> tuple[str, ...]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(
                "SELECT user_id FROM group_notification_subscriptions WHERE conversation_id = ? ORDER BY user_id",
                (conversation_id,),
            ).fetchall()
        return tuple(user_id for (user_id,) in rows)
