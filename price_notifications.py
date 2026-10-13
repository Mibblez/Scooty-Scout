import sqlite3
import time
import logging

import functools

import globals
from bot_utilities import usage_error, unknown_coin
from price_alerts import PriceAlerts

logger = logging.getLogger("scooty_scout")


def initialize_db():
    connection = sqlite3.connect('notifications.db')
    cursor = connection.cursor()

    command1 = 'CREATE TABLE IF NOT EXISTS ' +\
               'users(user_id INTEGER PRIMARY KEY, name TEXT)'

    command2 = 'CREATE TABLE IF NOT EXISTS ' +\
               'price_notifications(' +\
               'notification_id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, user_id INTEGER, ' +\
               'notify_at FLOAT, direction CHAR,' +\
               'FOREIGN KEY(user_id) REFERENCES users(user_id))'

    command3 = 'CREATE TABLE IF NOT EXISTS ' +\
               'at_everyone_notifications(group_chat_id INTEGER PRIMARY KEY, to_notify TEXT)'

    cursor.execute(command1)
    cursor.execute(command2)
    cursor.execute(command3)

    connection.commit()
    connection.close()


# Wrapper that creates a cursor for notifications.db and passes it down to func
# Closes the connection to the db and commits any changes once func returns
def uses_notification_db(func):
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        connection = sqlite3.connect('notifications.db')
        cursor = connection.cursor()

        # Call func with cursor, passing along any other args to it as well
        func(cursor, *args, **kwargs)

        connection.commit()
        connection.close()

    return wrapped


@globals.bot.message_handler(commands=['notify_me'])
@uses_notification_db
def at_everyone_opt_in(cursor, message):
    if message.chat.type == 'private':
        return

    chat_id = message.chat.id

    cursor.execute(f'SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id={chat_id}')
    if (result := cursor.fetchone()) is not None:
        user_ids = result[0]

        if str(message.from_user.id) in user_ids:
            globals.bot.reply_to(message, "You're already recieving @everyone notifiactions")
            return

        # Append the user's first name and ID to the group's notification entry
        user_ids += f';{message.from_user.first_name}|{message.from_user.id}'
        cursor.execute("UPDATE at_everyone_notifications "
                       f"SET to_notify = '{user_ids}' WHERE group_chat_id = '{chat_id}'")
    else:
        # A db entry does not exist for this group chat. Create one
        cursor.execute('INSERT INTO at_everyone_notifications VALUES '
                       f"({chat_id}, '{message.from_user.first_name}|{message.from_user.id}')")

    globals.bot.reply_to(message, "You will now be notified when someone uses the /everyone command")


@globals.bot.message_handler(commands=["dont_notify_me"])
@uses_notification_db
def at_everyone_opt_out(cursor, message):
    if message.chat.type == 'private':
        return

    chat_id = message.chat.id

    cursor.execute(f'SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id={chat_id}')
    if (result := cursor.fetchone()) is not None:
        user_ids = result[0]

        if str(message.from_user.id) in user_ids:
            # Remove the user's first name and ID from the group's notification entry
            user_ids_new = ';'.join(list(filter(lambda x: str(message.from_user.id) not in x, user_ids.split(';'))))
            cursor.execute("UPDATE at_everyone_notifications "
                           f"SET to_notify = '{user_ids_new}' WHERE group_chat_id = '{chat_id}'")

    globals.bot.reply_to(message, "You won't be notified when someone uses the /everyone command")


@globals.bot.message_handler(commands=['check_notifications', 'cnot'])
@uses_notification_db
def check_notifications(cursor, message):
    cursor.execute(f"SELECT coin, notify_at FROM price_notifications WHERE user_id={message.from_user.id}")
    result = cursor.fetchall()

    if result == []:
        # No notifications are set
        globals.bot.reply_to(message, "No notifications set")
        return

    response = ""

    for coin, notify_at in result:
        response += f"{coin} at ${notify_at}\n"

    globals.bot.reply_to(message, response)


@globals.bot.message_handler(commands=['delete_notification', 'dnot'])
@uses_notification_db
def delete_notification(cursor, message):
    request = message.text.split()[1:2] if len(message.text.split()) == 2 else ''

    if request == '':
        # Too many or too few args
        globals.bot.send_message(message.chat.id, usage_error('/delete_notification COIN_NAME'))
        return

    coin = request[0].upper()
    if coin not in globals.cryptos_json:
        # Given a coin name thats not in the JSON file
        globals.bot.send_message(message.chat.id, unknown_coin(request, globals.cryptos_json))
        return

    user_id = message.from_user.id

    cursor.execute(f"SELECT notification_id from price_notifications WHERE user_id={user_id} AND coin='{coin}'")
    if (cursor.fetchone() is None):
        globals.bot.reply_to(message, f"You don't have a notification set for {coin}")
        return

    cursor.execute(f"DELETE FROM price_notifications WHERE user_id={user_id} AND coin='{coin}'")

    globals.bot.reply_to(message, f"Notification for {coin} deleted")


def check_price_notifications(alerts: PriceAlerts):
    while True:
        try:
            for notification in alerts.due_notifications():
                try:
                    globals.bot.send_message(notification.user_id, notification.message())
                    alerts.acknowledge(notification.notification_id)
                except Exception:
                    logger.exception('Telegram price notification %s failed; retaining it for retry',
                                     notification.notification_id)
        except Exception:
            logger.exception('Telegram price notification check failed')
        time.sleep(900)
