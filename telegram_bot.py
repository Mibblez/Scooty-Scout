from __future__ import unicode_literals
import os
import pprint as pp
import sys
from dotenv import load_dotenv
import telebot
import json
import random
import time
import re
import sqlite3
import shutil
import requests

from itertools import chain
from ast import literal_eval
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects

from threading import Thread

import yt_dlp

from backend_config import Backend, get_backend
from bot_application import BotApplication, CoinCreationError, CoinUpdateError
import globals
from logging_setup import configure_logging
from bot_utilities import usage_error, unknown_coin, log_to_disk
from bot_utilities import UserState, TwitterVideoLogger
from telegram_adapter import TelegramAdapter, context_from_message

logger = configure_logging()

# Create necessary folders if they don't exist
necessary_dirs = ["misc_commands/", "media/", "media/user_media/"]
for dir in necessary_dirs:
    if not os.path.exists(dir):
        os.mkdir(dir)

load_dotenv()
if get_backend() is not Backend.TELEGRAM:
    logger.error("telegram_bot.py can only start when BOT_BACKEND=telegram; use main.py")
    sys.exit(1)

TELEGRAM_API_KEY = os.getenv("TELEGRAM_API_KEY")
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")

# Read ADMIN_IDS from .env and make sure it is a list of positive integers
try:
    ADMIN_IDS = literal_eval(os.getenv("ADMIN_IDS"))
    for id in ADMIN_IDS:
        if type(id) != int:
            raise ValueError("ValueError: ADMIN_IDS contains a non-interger value")
        elif id < 0:
            raise ValueError("ValueError: ADMIN_IDS cannot contain negetive intergers as those are not valid IDs")
except (TypeError, ValueError, SyntaxError) as err:
    logger.error("ADMIN_IDS .env variable missing or malformed: %s", err)
    logger.error("ADMIN_IDS should be a list of integers, such as [1, 2, 3]")
    sys.exit(1)

if None in [TELEGRAM_API_KEY, CMC_API_KEY, ETHERSCAN_API_KEY]:
    logger.error(
        "Missing API key(s) in .env: TELEGRAM_API_KEY, " "COINMARKETCAP_API_KEY and ETHERSCAN_API_KEY are required"
    )
    sys.exit(1)

if not os.path.exists("cryptos.json"):
    logger.error("cryptos.json not found; create it from cryptos_example.json")
    sys.exit(1)

json_file = open("cryptos.json")
cryptos_json = json.load(json_file)

bot = telebot.TeleBot(TELEGRAM_API_KEY)

# Have to initilize globals before importing files that have telebot decorators
globals.initilize(bot, cryptos_json, CMC_API_KEY)
import price_notifications
from price_notifications import uses_notification_db

user_states = {}

application = BotApplication(cryptos_json, CMC_API_KEY, notification_path="notifications.db")
TelegramAdapter(bot, application).register()


@bot.message_handler(commands=["dextools"])
def dextools(message):
    request = message.text.split()[1] if len(message.text.split()) == 2 else ""

    if request == "":
        bot.send_message(message.chat.id, "https://www.dextools.io/app/")
        return

    if request in cryptos_json:
        bot.send_message(message.chat.id, "wip")


@bot.message_handler(commands=["wen", "WEN"])
def wen(message):
    request = (message.text.split()[1] if len(message.text.split()) == 2 else "").lower()

    if request == "":
        return

    if request == "lambo":
        lambo_models = [
            "https://www.lamborghini.com/en-en/models/aventador/aventador-svj",
            "https://www.lamborghini.com/en-en/models/aventador/aventador-svj-roadster",
            "https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae",
            "https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae-roadster",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-evo",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-spyder",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd-spyder",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-fluo-capsule",
            "https://www.lamborghini.com/en-en/models/huracan/huracan-sto",
            "https://ezgo.txtsv.com/personal/golfcarts/freedom-rxv",
        ]

        # Reply with a link to a random lambo model from the lambo_models list
        bot.reply_to(message, lambo_models[random.randrange(len(lambo_models))])
    elif request == "moon":
        replies = ["Ask Musk Daddy\n\nhttps://twitter.com/elonmusk", "Soon", "HODL", "Ask Rob", "WEN MOON?"]

        # Reply with something stupid from the replies list
        bot.reply_to(message, replies[random.randrange(len(replies))])
        if os.path.exists("media/wen_moon.ogg"):
            bot.send_audio(message.chat.id, audio=open("media/wen_moon.ogg", "rb"))
    elif request == "aston":
        aston_models = [
            "https://www.astonmartin.com/en-us/models/aston-martin-valkyrie",
            "https://www.astonmartin.com/en-us/models/dbx",
            "https://www.astonmartin.com/en-us/models/new-vantage",
            "https://www.astonmartin.com/en-us/models/db11",
            "https://www.astonmartin.com/en-us/models/dbs-superleggera",
        ]
        bot.reply_to(message, aston_models[random.randrange(len(aston_models))])


@bot.message_handler(commands=["start"])
def start_bot(message):
    user_id = message.from_user.id

    connection = sqlite3.connect("notifications.db")
    cursor = connection.cursor()

    # Create new user in user db if not already present
    cursor.execute(f"SELECT user_id FROM users WHERE user_id={user_id}")
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO users VALUES " f"({user_id}, '{message.from_user.first_name} {message.from_user.last_name}')"
        )

    connection.commit()
    connection.close()

    bot.reply_to(message, "Henlo")


# TODO:  Different gas amounts with subcommands(normal transaction, uniswap, erc20, etc)
@bot.message_handler(commands=["ethgas"])
def ethgas(message):
    gas_url = "https://api.etherscan.io/api"
    gas_parameters = {"module": "gastracker", "action": "gasoracle", "apikey": ETHERSCAN_API_KEY}

    stats_url = "https://api.etherscan.io/api"
    stats_parameters = {"module": "stats", "action": "ethprice", "apikey": ETHERSCAN_API_KEY}

    session = Session()

    try:
        gas_response = session.get(gas_url, params=gas_parameters)
        gas_data = json.loads(gas_response.text)["result"]

        stats_response = session.get(stats_url, params=stats_parameters)
        stats_data = json.loads(stats_response.text)["result"]
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        bot.send_message(message.chat.id, "Could not reach API. Try again later.")
        logger.warning("Etherscan gas request failed: %s", type(e).__name__)
        return

    gwei_to_usd = 0.000000001 * float(stats_data["ethusd"])
    uniswap_gas_limit = 152000

    safe_gas_usd = round(float(gas_data["SafeGasPrice"]) * gwei_to_usd * uniswap_gas_limit, 4)
    proposed_gas_usd = round(float(gas_data["ProposeGasPrice"]) * gwei_to_usd * uniswap_gas_limit, 4)
    fast_gas_usd = round(float(gas_data["FastGasPrice"]) * gwei_to_usd * uniswap_gas_limit, 4)

    bot_message = (
        f"Uniswap Gas ({format(uniswap_gas_limit, ',')} gas limit)\n"
        + f"Safe: {gas_data['SafeGasPrice']} gwei (${safe_gas_usd})\n"
        + f"Proposed: {gas_data['ProposeGasPrice']} gwei (${proposed_gas_usd})\n"
        + f"Fast: {gas_data['FastGasPrice']} gwei (${fast_gas_usd})"
    )

    bot.send_message(message.chat.id, bot_message)


@bot.message_handler(
    func=lambda message: re.match("^/(nmc|new_media_command)$", message.caption.split()[0]), content_types=["photo"]
)
def new_media_command(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Only admins can make new commands")
        return

    message_split = message.caption.split()

    command_name = ""
    command_file_name = ""

    if len(message_split) == 2:
        command_name = message_split[1]
        command_file_name = "misc_commands/user_commands.py"
    elif len(message_split) == 3:
        command_name = message_split[1]
        command_file_name = f"misc_commands/{message_split[2]}.py"
        if not os.path.exists(command_file_name):
            # Don't allow users to create new files
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

    # Make sure no file with the same name exists in the media folder
    for file_path in chain(os.scandir("media/"), os.scandir("media/user_media/")):
        if os.path.splitext(os.path.basename(file_path))[0].lower() == command_name.lower():
            bot.send_message(message.chat.id, f"Cannot create /{command_name}. Command already exists")
            return

    # Get attached file
    file_info = bot.get_file(message.photo[-1].file_id)
    file = requests.get(
        "https://api.telegram.org/file/bot{0}/{1}".format(TELEGRAM_API_KEY, file_info.file_path), stream=True
    )

    # Save attached file to disk
    with open(f"media/user_media/{command_name}.jpg", "wb") as f:
        shutil.copyfileobj(file.raw, f)

    command_str = (
        f"\n\n@bot.message_handler(commands=['{command_name}'])\n"
        + f"def uc_{command_name}(message):\n"
        + f"    bot.send_photo(message.chat.id, open('media/user_media/{command_name}.jpg', 'rb'))\n"
    )

    # Feed command_str to the interpreter so that the command is available right away
    exec(command_str)

    # Append command to command file
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

    # Make sure no command with the same name exists in the media folder
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
            + f"def uc_{command_name}(message):\n"
            + f"    bot.send_video(message.chat.id, open('media/user_media/{file_name}', 'rb'))\n"
        )

        exec(command_str)

        # Append command to command file
        with open("misc_commands/user_commands.py", "a+") as command_file:
            command_file.write(command_str)


@bot.message_handler(commands=["list_commands", "lc"])
def list_commands_in_file(message, dir="misc_commands"):
    if not os.path.exists(dir):
        return

    request = message.text.split()[1] if len(message.text.split()) == 2 else ""

    # Given a command file that does not exist or too many or too few args
    if (request + ".py") not in os.listdir(dir) or request == "":
        response = "Usage: /list_commands COMMANDS_FILE\nKnown command files: "

        # Iterate over directories containing command files and strip the file extension from them
        python_files = list(filter(lambda file: file.endswith(".py"), os.listdir(dir)))
        python_files = [os.path.splitext(x)[0] for x in python_files]

        response += " | ".join(python_files)
        bot.send_message(message.chat.id, response)

        return

    with open(f"{dir}/{request}.py", "r") as f:
        commands = ""

        # Iterate over every bot command line
        for line in (x for x in f if x.startswith("@bot.")):
            matches = re.findall(r"['|\"](.*?)['|\"]", line)
            commands += (" | ".join(matches)) + " /// "

    bot.send_message(message.chat.id, f"Known commands in {request}:\n{commands}")


# Load bot commands from each python file in misc_commands directory
for command_file in filter(lambda file: file.endswith(".py"), os.listdir("misc_commands")):
    exec(open(f"misc_commands/{command_file}").read())


def handle_new_crypto(message):
    user_id = message.from_user.id

    # Check if the user is currently using a stated command
    if user_state := user_states.get(user_id):
        return True if user_state.current_command == "new_crypto" else False

    # See if the user is starting this command
    starting_command = message.text.split()[0] == "/new_crypto"

    if starting_command and user_id in ADMIN_IDS:
        user_states[user_id] = UserState("new_crypto")
        return True

    return False


@bot.message_handler(func=handle_new_crypto)
def new_crypto(message):
    user_id = message.from_user.id
    command_state = user_states[user_id].state

    if command_state == 0:
        identifier = message.text.split()[1] if len(message.text.split()) == 2 else ""
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

        user_states[user_id].new_crypto_tmp = candidate
        user_states[user_id].state = 1
        bot.send_message(message.chat.id, f"{candidate.preview()}\n\nIs this correct? (y/n)")
        return

    answer = message.text.strip().upper() if message.text else ""
    if answer == "Y":
        candidate = user_states[user_id].new_crypto_tmp
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
    user_id = message.from_user.id

    # Check if the user is currently using a stated command
    if user_state := user_states.get(user_id):
        return True if user_state.current_command == "update_crypto" else False

    # See if the user is starting this command
    starting_command = message.text.split()[0] == "/update_crypto"

    if starting_command and user_id in ADMIN_IDS:
        user_states[user_id] = UserState("update_crypto")
        return True

    return False


@bot.message_handler(func=handle_update_crypto)
def update_crypto(message):
    user_id = message.from_user.id

    command_state = user_states[user_id].state

    if command_state == 0:
        coin_symbol = (message.text.split()[1] if len(message.text.split()) == 2 else "").upper()

        if coin_symbol == "":
            bot.send_message(message.chat.id, usage_error("/update_crypto COIN_SYMBOL"))
            del user_states[user_id]
            return

        if coin_symbol not in cryptos_json:
            bot.reply_to(message, f"Cannot update coin: unknown coin {coin_symbol}")
            del user_states[user_id]
            return

        metadata = cryptos_json[coin_symbol].get("INFO") or {}
        user_states[user_id].new_crypto_tmp = [coin_symbol, metadata]

        reply = f"--- {coin_symbol} Info ---\n"
        index = 0
        for k, v in metadata.items():
            reply += f"[{index}] - {k}: {v}\n"
            index += 1

        reply += (
            f"Enter the index of the entry you want to change or enter {index} to add a new entry.\n"
            + "Enter anything else to abort."
        )
        user_states[user_id].state = 1

        bot.reply_to(message, reply)
    elif command_state == 1:
        answer = message.text if len(message.text.split()) == 1 else ""

        current_entries_len = len(user_states[user_id].new_crypto_tmp[1])

        if (not answer.isdigit()) or (int(answer) < 0) or (int(answer) > current_entries_len):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        answer = int(answer)

        if current_entries_len == answer:
            # User is making a new entry
            bot.send_message(message.chat.id, "Enter a name for the new entry or enter ABORT to cancel.")
            user_states[user_id].state = 2
        else:
            # User is updating an existing entry
            value_to_change = list(user_states[user_id].new_crypto_tmp[1])[answer]
            bot.send_message(message.chat.id, f"Enter a new value for {value_to_change} or enter ABORT to cancel.")
            user_states[user_id].additional_command_info = value_to_change
            user_states[user_id].state = 3
    elif command_state == 2:
        answer = message.text if message.text is not None else ""

        if (answer == "") or (answer.upper() == "ABORT"):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        user_states[user_id].additional_command_info = answer
        bot.send_message(message.chat.id, f"Enter a value for {answer}.")
        user_states[user_id].state = 3
    elif command_state == 3:
        answer = message.text if message.text is not None else ""

        if answer == "" or (answer.upper() == "ABORT"):
            del user_states[user_id]
            bot.reply_to(message, "Aborting command.")
            return

        coin_symbol = user_states[user_id].new_crypto_tmp[0]
        field = user_states[user_id].additional_command_info
        try:
            change = application.prepare_coin_update(coin_symbol, field, answer)
        except CoinUpdateError as error:
            bot.reply_to(message, str(error))
            del user_states[user_id]
            return
        user_states[user_id].new_crypto_tmp = change
        bot.send_message(message.chat.id, f"{change.preview()}\n\nIs this information correct? (y/n)")
        user_states[user_id].state = 4
    elif command_state == 4:
        answer = (message.text if len(message.text.split()) == 1 else "").upper()

        if answer == "Y":
            change = user_states[user_id].new_crypto_tmp
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
    if (
        message.from_user.id not in ADMIN_IDS
        or not message.text.startswith("/everyone ")
        or message.chat.type == "private"
    ):
        return False

    return True


@bot.message_handler(func=handle_at_everyone)
@uses_notification_db
def at_everyone(cursor, message):
    chat_id = message.chat.id

    # Get the first name and user ID for all users in this group who are registered for /everyone notifications
    cursor.execute(f"SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id={chat_id}")

    if (result := cursor.fetchone()) is not None:
        # User entries are split up by semicolons
        user_entries = result[0].split(";")

        response = ""
        for user_entry in user_entries:
            # First name and user ID are seperated by a |
            first_name, user_id = user_entry.split("|")

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

    # Keep Telegram polling isolated so HTTP timeouts do not prevent CTRL-C.
    telegram_polling_thread = Thread(target=message_polling)
    telegram_polling_thread.start()

    price_checker_thread = Thread(target=run_price_checker)
    price_checker_thread.start()


if __name__ == "__main__":
    run()
