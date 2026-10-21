import json
import os
import re
import shutil
import sqlite3
import sys
import time
from ast import literal_eval
from contextlib import closing
from itertools import chain
from threading import Thread

import requests
import telebot
import yt_dlp
from dotenv import load_dotenv

import globals
from backend_config import Backend, get_backend
from bot_application import BotApplication, CoinCreationError, CoinUpdateError
from bot_utilities import UserState, TwitterVideoLogger, log_to_disk, usage_error
from logging_setup import configure_logging
from telegram_adapter import TelegramAdapter, context_from_message

logger = configure_logging()

for directory in ("misc_commands", "media/user_media"):
    os.makedirs(directory, exist_ok=True)

load_dotenv()
if get_backend() is not Backend.TELEGRAM:
    logger.error("telegram_bot.py can only start when BOT_BACKEND=telegram; use main.py")
    sys.exit(1)

TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")

try:
    ADMIN_IDS = literal_eval(os.getenv("ADMIN_IDS"))
    for admin_id in ADMIN_IDS:
        if type(admin_id) is not int:
            raise ValueError("ADMIN_IDS contains a non-integer value")
        if admin_id < 0:
            raise ValueError("ADMIN_IDS cannot contain negative integers")
except (TypeError, ValueError, SyntaxError) as err:
    logger.error("ADMIN_IDS .env variable missing or malformed: %s", err)
    logger.error("ADMIN_IDS should be a list of integers, such as [1, 2, 3]")
    sys.exit(1)

if not TELEGRAM_API_KEY or not CMC_API_KEY:
    logger.error("Missing API key(s) in .env: TELEGRAM_API_KEY and COINMARKETCAP_API_KEY are required")
    sys.exit(1)

if not os.path.exists("cryptos.json"):
    logger.error("cryptos.json not found; create it from cryptos_example.json")
    sys.exit(1)

with open("cryptos.json") as json_file:
    cryptos_json = json.load(json_file)

bot = telebot.TeleBot(TELEGRAM_API_KEY)

# Command modules use the bot globals to register handlers during import.
globals.initilize(bot, cryptos_json, CMC_API_KEY)
import price_notifications
from price_notifications import uses_notification_db

user_states: dict[int, UserState] = {}

application = BotApplication(
    cryptos_json, CMC_API_KEY, notification_path="notifications.db", etherscan_api_key=ETHERSCAN_API_KEY
)
TelegramAdapter(bot, application).register()


@bot.message_handler(commands=["dextools"])
def dextools(message):
    arguments = message.text.split()
    request = arguments[1] if len(arguments) == 2 else ""

    if request == "":
        bot.send_message(message.chat.id, "https://www.dextools.io/app/")
        return

    if request in cryptos_json:
        bot.send_message(message.chat.id, "wip")


@bot.message_handler(commands=["start"])
def start_bot(message):
    user_id = message.from_user.id
    name = f"{message.from_user.first_name} {message.from_user.last_name}"
    with closing(sqlite3.connect("notifications.db")) as connection, connection:
        connection.execute("INSERT OR IGNORE INTO users(user_id, name) VALUES (?, ?)", (user_id, name))

    bot.reply_to(message, "Henlo")


@bot.message_handler(
    func=lambda message: re.match("^/(nmc|new_media_command)$", message.caption.split()[0]), content_types=["photo"]
)
def new_media_command(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Only admins can make new commands")
        return

    message_split = message.caption.split()

    if len(message_split) == 2:
        command_name = message_split[1]
        command_file_name = "misc_commands/user_commands.py"
    elif len(message_split) == 3:
        command_name = message_split[1]
        command_file_name = f"misc_commands/{message_split[2]}.py"
        if not os.path.exists(command_file_name):
            return
    else:
        bot.send_message(message.chat.id, usage_error("/new_media_command COMMAND_NAME COMMAND_FILE=user_commands"))
        return

    if not re.match("^[^_][A-Za-z0-9_]*$", command_name):
        bot.reply_to(
            message,
            "Command name must only contain aplhanumeric characters and underscores "
            "and cannot start with an underscore",
        )
        return

    for file_path in chain(os.scandir("media/"), os.scandir("media/user_media/")):
        if os.path.splitext(os.path.basename(file_path))[0].lower() == command_name.lower():
            bot.send_message(message.chat.id, f"Cannot create /{command_name}. Command already exists")
            return

    file_info = bot.get_file(message.photo[-1].file_id)
    file = requests.get(
        "https://api.telegram.org/file/bot{0}/{1}".format(TELEGRAM_API_KEY, file_info.file_path), stream=True
    )

    with open(f"media/user_media/{command_name}.jpg", "wb") as f:
        shutil.copyfileobj(file.raw, f)

    command_str = (
        f"\n\n@bot.message_handler(commands=['{command_name}'])\n"
        f"def uc_{command_name}(message):\n"
        f"    bot.send_photo(message.chat.id, open('media/user_media/{command_name}.jpg', 'rb'))\n"
    )

    # Register the handler now; the saved definition restores it after restart.
    exec(command_str)

    with open(command_file_name, "a+") as command_file:
        command_file.write(command_str)

    bot.reply_to(message, f"New command created: /{command_name}")

    log_to_disk(f"Added new media command /{command_name}", "/new_media_command", context_from_message(message))


@bot.message_handler(commands=["new_twitter_video_command", "ntv"])
def new_media_command_twitter_video(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Only admins can make new commands")
        return

    message_split = message.text.split()

    if len(message_split) != 3:
        bot.send_message(message.chat.id, usage_error("/new_twitter_video_command COMMAND_NAME TWITTER_VIDEO_URL"))
        return

    command_name = message_split[1]
    twitter_vid_url = message_split[2]

    if not re.match("^http[s]?://twitter.com/i/status/[0-9]+$", twitter_vid_url):
        bot.reply_to(
            message, "Invalid URL. Get the URL for the video my right clicking it" "and clicking 'Copy Video Address'"
        )
        return

    if not re.match("^[^_][A-Za-z0-9_]*$", command_name):
        bot.reply_to(
            message,
            "Command name must only contain aplhanumeric characters and underscores "
            "and cannot start with an underscore",
        )
        return

    for file_path in chain(os.scandir("media/"), os.scandir("media/user_media/")):
        if os.path.splitext(os.path.basename(file_path))[0].lower() == command_name.lower():
            bot.send_message(message.chat.id, f"Cannot create /{command_name}. Command already exists")
            return

    ydl_opts = {
        "outtmpl": f"media/user_media/{command_name}" + ".%(ext)s",
        "logger": TwitterVideoLogger(),
        "progress_hooks": [twitter_download_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([twitter_vid_url])
    except yt_dlp.utils.DownloadError:
        logger.warning(
            "Video command /%s download failed for user %s",
            command_name,
            message.from_user.id,
        )
        bot.reply_to(message, "Could not download video. Maybe the provided URL is invalid?")
        return

    bot.reply_to(message, f"New command created: /{command_name}")

    log_to_disk(
        f"Added new twitter video command /{command_name}", "/new_twitter_video_command", context_from_message(message)
    )


def twitter_download_hook(d):
    if d["status"] == "finished":
        file_name = os.path.basename(d["filename"])
        command_name, file_extension = os.path.splitext(file_name)

        if file_extension != ".mp4":
            raise yt_dlp.utils.DownloadError("Invalid file extension")

        command_str = (
            f"\n\n@bot.message_handler(commands=['{command_name}'])\n"
            f"def uc_{command_name}(message):\n"
            f"    bot.send_video(message.chat.id, open('media/user_media/{file_name}', 'rb'))\n"
        )

        exec(command_str)

        with open("misc_commands/user_commands.py", "a+") as command_file:
            command_file.write(command_str)


@bot.message_handler(commands=["list_commands", "lc"])
def list_commands_in_file(message, dir="misc_commands"):
    if not os.path.exists(dir):
        return

    arguments = message.text.split()
    request = arguments[1] if len(arguments) == 2 else ""

    if (request + ".py") not in os.listdir(dir) or request == "":
        response = "Usage: /list_commands COMMANDS_FILE\nKnown command files: "

        python_files = [os.path.splitext(file)[0] for file in os.listdir(dir) if file.endswith(".py")]

        response += " | ".join(python_files)
        bot.send_message(message.chat.id, response)

        return

    with open(f"{dir}/{request}.py") as command_file:
        commands = ""

        for line in command_file:
            if not line.startswith("@bot."):
                continue
            matches = re.findall(r"['|\"](.*?)['|\"]", line)
            commands += " | ".join(matches) + " /// "

    bot.send_message(message.chat.id, f"Known commands in {request}:\n{commands}")


# Restore saved Telegram handlers at startup.
for command_file_name in os.listdir("misc_commands"):
    if command_file_name.endswith(".py"):
        with open(f"misc_commands/{command_file_name}") as command_file:
            exec(command_file.read())


def _handles_stateful_command(message, command_name):
    """Route replies to the user's active command."""
    user_id = message.from_user.id

    if user_state := user_states.get(user_id):
        return user_state.current_command == command_name

    if message.text.split()[0] == f"/{command_name}" and user_id in ADMIN_IDS:
        user_states[user_id] = UserState(command_name)
        return True

    return False


def handle_new_crypto(message):
    return _handles_stateful_command(message, "new_crypto")


@bot.message_handler(func=handle_new_crypto)
def new_crypto(message):
    user_id = message.from_user.id
    user_state = user_states[user_id]

    if user_state.state == 0:
        arguments = message.text.split()
        identifier = arguments[1] if len(arguments) == 2 else ""
        if not identifier:
            bot.send_message(message.chat.id, usage_error("/new_crypto [CONTRACT_ADDRESS|SYMBOL]"))
            del user_states[user_id]
            return
        try:
            candidate = application.prepare_new_coin(identifier)
        except CoinCreationError as error:
            bot.reply_to(message, str(error))
            del user_states[user_id]
            return
        except Exception:
            logger.exception("Telegram /new_crypto lookup failed")
            bot.reply_to(message, "Could not look up that coin. Try again later.")
            del user_states[user_id]
            return

        user_state.new_crypto_tmp = candidate
        user_state.state = 1
        bot.send_message(message.chat.id, f"{candidate.preview()}\n\nIs this correct? (y/n)")
        return

    answer = message.text.strip().upper() if message.text else ""
    if answer == "Y":
        candidate = user_state.new_crypto_tmp
        try:
            application.add_coin(candidate)
        except (CoinCreationError, OSError) as error:
            bot.reply_to(message, str(error))
        else:
            bot.reply_to(message, "Success. The new coin has been added to the bot.")
            log_to_disk(f"Added {candidate.symbol} to the bot", "/new_crypto", context_from_message(message))
    else:
        bot.reply_to(message, "Aborting command.")
    del user_states[user_id]


def handle_update_crypto(message):
    return _handles_stateful_command(message, "update_crypto")


@bot.message_handler(func=handle_update_crypto)
def update_crypto(message):
    user_id = message.from_user.id
    user_state = user_states[user_id]
    command_state = user_state.state

    if command_state == 0:
        arguments = message.text.split()
        coin_symbol = (arguments[1] if len(arguments) == 2 else "").upper()

        if coin_symbol == "":
            bot.send_message(message.chat.id, usage_error("/update_crypto COIN_SYMBOL"))
            del user_states[user_id]
            return

        if coin_symbol not in cryptos_json:
            bot.reply_to(message, f"Cannot update coin: unknown coin {coin_symbol}")
            del user_states[user_id]
            return

        metadata = cryptos_json[coin_symbol].get("INFO") or {}
        user_state.new_crypto_tmp = [coin_symbol, metadata]

        reply = f"--- {coin_symbol} Info ---\n"
        for index, (field, value) in enumerate(metadata.items()):
            reply += f"[{index}] - {field}: {value}\n"

        reply += (
            f"Enter the index of the entry you want to change or enter {len(metadata)} to add a new entry.\n"
            "Enter anything else to abort."
        )
        user_state.state = 1

        bot.reply_to(message, reply)
    elif command_state == 1:
        answer = message.text if len(message.text.split()) == 1 else ""

        metadata = user_state.new_crypto_tmp[1]

        if not answer.isdigit() or not 0 <= int(answer) <= len(metadata):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        answer = int(answer)

        if answer == len(metadata):
            bot.send_message(message.chat.id, "Enter a name for the new entry or enter ABORT to cancel.")
            user_state.state = 2
        else:
            value_to_change = list(metadata)[answer]
            bot.send_message(message.chat.id, f"Enter a new value for {value_to_change} or enter ABORT to cancel.")
            user_state.additional_info = value_to_change
            user_state.state = 3
    elif command_state == 2:
        answer = message.text if message.text is not None else ""

        if (answer == "") or (answer.upper() == "ABORT"):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        user_state.additional_info = answer
        bot.send_message(message.chat.id, f"Enter a value for {answer}.")
        user_state.state = 3
    elif command_state == 3:
        answer = message.text if message.text is not None else ""

        if answer == "" or (answer.upper() == "ABORT"):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        coin_symbol = user_state.new_crypto_tmp[0]
        field = user_state.additional_info
        try:
            change = application.prepare_coin_update(coin_symbol, field, answer)
        except CoinUpdateError as error:
            bot.reply_to(message, str(error))
            del user_states[user_id]
            return
        user_state.new_crypto_tmp = change
        bot.send_message(message.chat.id, f"{change.preview()}\n\nIs this information correct? (y/n)")
        user_state.state = 4
    elif command_state == 4:
        answer = (message.text if len(message.text.split()) == 1 else "").upper()

        if answer == "Y":
            change = user_state.new_crypto_tmp
            try:
                application.update_coin(change)
            except (CoinUpdateError, OSError) as error:
                bot.reply_to(message, str(error))
            else:
                bot.reply_to(message, "Coin successfully updated")
                log_to_disk(f"Updated {change.symbol}: {change.field}", "/update_crypto", context_from_message(message))
        else:
            bot.reply_to(message, "Aborting command.")

        del user_states[user_id]


def handle_at_everyone(message):
    return (
        message.from_user.id in ADMIN_IDS and message.text.startswith("/everyone ") and message.chat.type != "private"
    )


@bot.message_handler(func=handle_at_everyone)
@uses_notification_db
def at_everyone(cursor, message):
    chat_id = message.chat.id

    cursor.execute("SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id = ?", (chat_id,))

    result = cursor.fetchone()
    if result is None or not result[0]:
        return

    response = ""
    for user_entry in result[0].split(";"):
        first_name, user_id = user_entry.rsplit("|", 1)
        response += f"[{first_name}](tg://user?id={user_id}) "

    bot.reply_to(message, response, parse_mode="Markdown")


def message_polling():
    logger.info("Telegram polling started")
    while True:
        try:
            bot.polling()
        except Exception as e:
            logger.error("Telegram polling failed: %s", type(e).__name__)

        time.sleep(1)


def run_price_checker():
    logger.info("Price checker started")
    try:
        price_notifications.check_price_notifications(application.price_alerts)
    except Exception as e:
        logger.error("Price checker stopped: %s", type(e).__name__)


def run() -> None:
    price_notifications.initialize_db()
    logger.info("Scooty Scout started")

    # Keep the main thread available for Ctrl+C while polling waits for HTTP responses.
    telegram_polling_thread = Thread(target=message_polling)
    telegram_polling_thread.start()

    price_checker_thread = Thread(target=run_price_checker)
    price_checker_thread.start()


if __name__ == "__main__":
    run()
