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

import globals
from logging_setup import configure_logging
from bot_utilities import cmc_id_map, get_coin_data, usage_error, unknown_coin, get_coin_info, log_to_disk
from bot_utilities import UserState, TwitterVideoLogger

logger = configure_logging()

# Create necessary folders if they don't exist
necessary_dirs = ['misc_commands/', 'media/', 'media/user_media/']
for dir in necessary_dirs:
    if not os.path.exists(dir):
        os.mkdir(dir)

load_dotenv()
TELEGRAM_API_KEY = os.getenv('TELEGRAM_API_KEY')
CMC_API_KEY = os.getenv('COINMARKETCAP_API_KEY')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY')

# Read ADMIN_IDS from .env and make sure it is a list of positive integers
try:
    ADMIN_IDS = literal_eval(os.getenv('ADMIN_IDS'))
    for id in ADMIN_IDS:
        if type(id) != int:
            raise ValueError('ValueError: ADMIN_IDS contains a non-interger value')
        elif id < 0:
            raise ValueError('ValueError: ADMIN_IDS cannot contain negetive intergers as those are not valid IDs')
except (TypeError, ValueError, SyntaxError) as err:
    logger.error("ADMIN_IDS .env variable missing or malformed: %s", err)
    logger.error("ADMIN_IDS should be a list of integers, such as [1, 2, 3]")
    sys.exit(1)

if None in [TELEGRAM_API_KEY, CMC_API_KEY, ETHERSCAN_API_KEY]:
    logger.error(
        "Missing API key(s) in .env: TELEGRAM_API_KEY, "
        "COINMARKETCAP_API_KEY and ETHERSCAN_API_KEY are required"
    )
    sys.exit(1)

if not os.path.exists('cryptos.json'):
    logger.error("cryptos.json not found; create it from cryptos_example.json")
    sys.exit(1)

json_file = open('cryptos.json')
cryptos_json = json.load(json_file)

bot = telebot.TeleBot(TELEGRAM_API_KEY)

# Have to initilize globals before importing files that have telebot decorators
globals.initilize(bot, cryptos_json, CMC_API_KEY)
import price_notifications
from price_notifications import uses_notification_db

user_states = {}
# new_crypto_tmp = {}
# additional_command_info = {}


@bot.message_handler(commands=['coins'])
def coins(message):
    bot.reply_to(message, 'Known coins:\n' + ' ; '.join([x for x in cryptos_json.keys()]))


# TODO: add has_dextools in each json entry. show dextools url if has_dextools is set to true
@bot.message_handler(commands=['info'])
def info(message):
    request = message.text.split()[1] if len(message.text.split()) == 2 else ''

    # Too many or too few args
    if request == '':
        usage_error(message, '/info COIN_NAME')
        return

    # Given a coin name thats not in the JSON file
    if request not in cryptos_json:
        unknown_coin(message, request)
        return

    response = ''

    requested_crypto_info = cryptos_json[request]["INFO"]

    for k, v in requested_crypto_info.items():
        response += f'{k} : {v}\n'

    if 'chain' in requested_crypto_info:
        if requested_crypto_info['chain'] == 'BSC':
            response += f"BSC Scan: https://www.bscscan.com/address/{requested_crypto_info['contract_id']}\n"
            response += f"Dextools: https://www.dextools.io/app/{requested_crypto_info['chain'].lower()}" +\
                f"/pair-explorer/{requested_crypto_info['contract_id']}"
        else:
            response += f"CMC: https://coinmarketcap.com/currencies/{cryptos_json[request]['cmc_name']}/"

    bot.send_message(message.chat.id, response)


@bot.message_handler(commands=['dextools'])
def dextools(message):
    request = message.text.split()[1] if len(message.text.split()) == 2 else ''

    if request == '':
        bot.send_message(message.chat.id, 'https://www.dextools.io/app/')
        return

    if request in cryptos_json:
        bot.send_message(message.chat.id, 'wip')


@bot.message_handler(commands=['wen', 'WEN'])
def wen(message):
    request = (message.text.split()[1] if len(message.text.split()) == 2 else '').lower()

    if request == '':
        return

    if request == 'lambo':
        lambo_models = ['https://www.lamborghini.com/en-en/models/aventador/aventador-svj',
                        'https://www.lamborghini.com/en-en/models/aventador/aventador-svj-roadster',
                        'https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae',
                        'https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae-roadster',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-evo',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-evo-spyder',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd-spyder',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-evo-fluo-capsule',
                        'https://www.lamborghini.com/en-en/models/huracan/huracan-sto',
                        'https://ezgo.txtsv.com/personal/golfcarts/freedom-rxv'
                        ]

        # Reply with a link to a random lambo model from the lambo_models list
        bot.reply_to(message, lambo_models[random.randrange(len(lambo_models))])
    elif request == 'moon':
        replies = ['Ask Musk Daddy\n\nhttps://twitter.com/elonmusk',
                   'Soon',
                   'HODL',
                   'Ask Rob',
                   'WEN MOON?']

        # Reply with something stupid from the replies list
        bot.reply_to(message, replies[random.randrange(len(replies))])
        if os.path.exists('media/wen_moon.ogg'):
            bot.send_audio(message.chat.id, audio=open('media/wen_moon.ogg', 'rb'))
    elif request == 'aston':
        aston_models = ['https://www.astonmartin.com/en-us/models/aston-martin-valkyrie',
                        'https://www.astonmartin.com/en-us/models/dbx',
                        'https://www.astonmartin.com/en-us/models/new-vantage',
                        'https://www.astonmartin.com/en-us/models/db11',
                        'https://www.astonmartin.com/en-us/models/dbs-superleggera']
        bot.reply_to(message, aston_models[random.randrange(len(aston_models))])


@bot.message_handler(commands=['start'])
def start_bot(message):
    user_id = message.from_user.id

    connection = sqlite3.connect('notifications.db')
    cursor = connection.cursor()

    # Create new user in user db if not already present
    cursor.execute(f"SELECT user_id FROM users WHERE user_id={user_id}")
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users VALUES '
                       f"({user_id}, '{message.from_user.first_name} {message.from_user.last_name}')")

    connection.commit()
    connection.close()

    bot.reply_to(message, "Henlo")


@bot.message_handler(commands=['price'])
def price(message):
    request = message.text.split()[1] if len(message.text.split()) == 2 else ''

    # Too many or too few args
    if request == '':
        usage_error(message, '/price COIN_NAME')
        return

    # Given a coin name thats not in the JSON file
    if request not in cryptos_json:
        unknown_coin(message, request)
        return

    coin_id = cryptos_json[request]["cmc_id"]
    coin_data = get_coin_data(coin_id, CMC_API_KEY)

    if coin_data is None:
        bot.send_message(message.chat.id, "Could not get the latest price. Try again later.")
        return

    latest_price = "{:.10f}".format(
        coin_data['data'][coin_id]['quote']['USD']['price'])

    percent_change_24h = float("{:.2f}".format(
        coin_data['data'][coin_id]['quote']['USD']['percent_change_24h']))

    movement_direction = '⬆️' if percent_change_24h > 0.0 else '⬇️'

    bot.send_message(message.chat.id, f"{request} Price: ${latest_price}\n"
                     f"{movement_direction} {percent_change_24h}% (24H)")


# TODO:  Different gas amounts with subcommands(normal transaction, uniswap, erc20, etc)
@bot.message_handler(commands=['ethgas'])
def ethgas(message):
    gas_url = 'https://api.etherscan.io/api'
    gas_parameters = {
        'module': 'gastracker',
        'action': 'gasoracle',
        'apikey': ETHERSCAN_API_KEY
    }

    stats_url = 'https://api.etherscan.io/api'
    stats_parameters = {
        'module': 'stats',
        'action': 'ethprice',
        'apikey': ETHERSCAN_API_KEY
    }

    session = Session()

    try:
        gas_response = session.get(gas_url, params=gas_parameters)
        gas_data = json.loads(gas_response.text)['result']

        stats_response = session.get(stats_url, params=stats_parameters)
        stats_data = json.loads(stats_response.text)['result']
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        bot.send_message(message.chat.id, "Could not reach API. Try again later.")
        logger.warning("Etherscan gas request failed: %s", type(e).__name__)
        return

    gwei_to_usd = 0.000000001 * float(stats_data['ethusd'])
    uniswap_gas_limit = 152000

    safe_gas_usd = round(float(gas_data['SafeGasPrice']) * gwei_to_usd * uniswap_gas_limit, 4)
    proposed_gas_usd = round(float(gas_data['ProposeGasPrice']) * gwei_to_usd * uniswap_gas_limit, 4)
    fast_gas_usd = round(float(gas_data['FastGasPrice']) * gwei_to_usd * uniswap_gas_limit, 4)

    bot_message = f"Uniswap Gas ({format(uniswap_gas_limit, ',')} gas limit)\n" +\
        f"Safe: {gas_data['SafeGasPrice']} gwei (${safe_gas_usd})\n" +\
        f"Proposed: {gas_data['ProposeGasPrice']} gwei (${proposed_gas_usd})\n" +\
        f"Fast: {gas_data['FastGasPrice']} gwei (${fast_gas_usd})"

    bot.send_message(message.chat.id, bot_message)


@bot.message_handler(func=lambda message: re.match('^/(nmc|new_media_command)$', message.caption.split()[0]),
                     content_types=['photo'])
def new_media_command(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, 'Only admins can make new commands')
        return

    message_split = message.caption.split()

    command_name = ''
    command_file_name = ''

    if len(message_split) == 2:
        command_name = message_split[1]
        command_file_name = 'misc_commands/user_commands.py'
    elif len(message_split) == 3:
        command_name = message_split[1]
        command_file_name = f'misc_commands/{message_split[2]}.py'
        if not os.path.exists(command_file_name):
            # Don't allow users to create new files
            return
    else:
        usage_error(message, "/new_media_command COMMAND_NAME COMMAND_FILE=user_commands")
        return

    if not re.match('^[^_][A-Za-z0-9_]*$', command_name):
        bot.reply_to(message, "Command name must only contain aplhanumeric characters and underscores "
                              "and cannot start with an underscore")
        return

    # Make sure no file with the same name exists in the media folder
    for file_path in chain(os.scandir('media/'), os.scandir('media/user_media/')):
        if os.path.splitext(os.path.basename(file_path))[0].lower() == command_name.lower():
            bot.send_message(message.chat.id, f'Cannot create /{command_name}. Command already exists')
            return

    # Get attached file
    file_info = bot.get_file(message.photo[-1].file_id)
    file = requests.get('https://api.telegram.org/file/bot{0}/{1}'.
                        format(TELEGRAM_API_KEY, file_info.file_path), stream=True)

    # Save attached file to disk
    with open(f'media/user_media/{command_name}.jpg', 'wb') as f:
        shutil.copyfileobj(file.raw, f)

    command_str = f"\n\n@bot.message_handler(commands=['{command_name}'])\n" +\
                  f"def uc_{command_name}(message):\n" +\
                  f"    bot.send_photo(message.chat.id, open('media/user_media/{command_name}.jpg', 'rb'))\n"

    # Feed command_str to the interpreter so that the command is available right away
    exec(command_str)

    # Append command to command file
    with open(command_file_name, 'a+') as command_file:
        command_file.write(command_str)

    bot.reply_to(message, f"New command created: /{command_name}")

    log_to_disk(f'Added new media command /{command_name}', '/new_media_command', message)


@bot.message_handler(commands=['new_twitter_video_command', 'ntv'])
def new_media_command_twitter_video(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, 'Only admins can make new commands')
        return

    message_split = message.text.split()

    if len(message_split) != 3:
        usage_error(message, "/new_twitter_video_command COMMAND_NAME TWITTER_VIDEO_URL")
        return

    command_name = message_split[1]
    twitter_vid_url = message_split[2]

    if not re.match('^http[s]?://twitter.com/i/status/[0-9]+$', twitter_vid_url):
        bot.reply_to(message, "Invalid URL. Get the URL for the video my right clicking it"
                              "and clicking 'Copy Video Address'")
        return

    if not re.match('^[^_][A-Za-z0-9_]*$', command_name):
        bot.reply_to(message, "Command name must only contain aplhanumeric characters and underscores "
                              "and cannot start with an underscore")
        return

    # Make sure no command with the same name exists in the media folder
    for file_path in chain(os.scandir('media/'), os.scandir('media/user_media/')):
        if os.path.splitext(os.path.basename(file_path))[0].lower() == command_name.lower():
            bot.send_message(message.chat.id, f'Cannot create /{command_name}. Command already exists')
            return

    ydl_opts = {'outtmpl': f"media/user_media/{command_name}" + ".%(ext)s",
                'logger': TwitterVideoLogger(),
                'progress_hooks': [twitter_download_hook]
                }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([twitter_vid_url])
    except yt_dlp.utils.DownloadError:
        logger.warning(
            "Video command /%s download failed for user %s",
            command_name, message.from_user.id,
        )
        bot.reply_to(message, "Could not download video. Maybe the provided URL is invalid?")
        return

    bot.reply_to(message, f"New command created: /{command_name}")

    log_to_disk(f'Added new twitter video command /{command_name}', '/new_twitter_video_command', message)


def twitter_download_hook(d):
    if d['status'] == 'finished':
        file_name = os.path.basename(d['filename'])
        command_name, file_extension = os.path.splitext(file_name)

        if file_extension != '.mp4':
            raise yt_dlp.utils.DownloadError("Invalid file extension")

        command_str = f"\n\n@bot.message_handler(commands=['{command_name}'])\n" +\
                      f"def uc_{command_name}(message):\n" +\
                      f"    bot.send_video(message.chat.id, open('media/user_media/{file_name}', 'rb'))\n"

        exec(command_str)

        # Append command to command file
        with open('misc_commands/user_commands.py', 'a+') as command_file:
            command_file.write(command_str)


@bot.message_handler(commands=['list_commands', 'lc'])
def list_commands_in_file(message, dir='misc_commands'):
    if not os.path.exists(dir):
        return

    request = message.text.split()[1] if len(message.text.split()) == 2 else ''

    # Given a command file that does not exist or too many or too few args
    if (request + '.py') not in os.listdir(dir) or request == '':
        response = 'Usage: /list_commands COMMANDS_FILE\nKnown command files: '

        # Iterate over directories containing command files and strip the file extension from them
        python_files = list(filter(lambda file: file.endswith('.py'), os.listdir(dir)))
        python_files = [os.path.splitext(x)[0] for x in python_files]

        response += ' | '.join(python_files)
        bot.send_message(message.chat.id, response)

        return

    with open(f'{dir}/{request}.py', 'r') as f:
        commands = ""

        # Iterate over every bot command line
        for line in (x for x in f if x.startswith('@bot.')):
            matches = re.findall(r"['|\"](.*?)['|\"]", line)
            commands += (' | '.join(matches)) + " /// "

    bot.send_message(message.chat.id, f"Known commands in {request}:\n{commands}")


# Load bot commands from each python file in misc_commands directory
for command_file in filter(lambda file: file.endswith('.py'), os.listdir('misc_commands')):
    exec(open(f"misc_commands/{command_file}").read())


def handle_new_crypto(message):
    user_id = message.from_user.id

    # Check if the user is currently using a stated command
    if user_state := user_states.get(user_id):
        return True if user_state.current_command == 'new_crypto' else False

    # See if the user is starting this command
    starting_command = message.text.split()[0] == '/new_crypto'

    if starting_command and user_id in ADMIN_IDS:
        user_states[user_id] = UserState('new_crypto')
        return True

    return False


@bot.message_handler(func=handle_new_crypto)
def new_crypto(message):
    user_id = message.from_user.id
    command_state = user_states[user_id].state

    if command_state == 0:
        crypto_to_add = (message.text.split()[1] if len(message.text.split()) == 2 else '')

        # Too many or too few args
        if crypto_to_add == '':
            usage_error(message, '/new_crypto [CONTRACT_ADDRESS|SYMBOL]')
            del user_states[user_id]
            return

        if crypto_to_add.startswith('0x'):
            # Given a contract address
            response = get_coin_info(crypto_to_add, CMC_API_KEY)
        else:
            # Given a crypto symbol
            response = cmc_id_map(crypto_to_add, CMC_API_KEY)
            if (response['status']['error_message'] is None) and (len(response['data']) == 1):
                # Only got one crypto. Can get its info right away
                response = get_coin_info(None, CMC_API_KEY, id=int(response['data'][0]['id']))
            else:
                bot_message = (f"Cannot add {crypto_to_add}, "
                               "found multiple cryptocurrencies matching the provided symbol.\n"
                               "Use a contract ID to add this coin.")
                bot.send_message(message.chat.id, bot_message)
                del user_states[user_id]
                return

        # Make sure a cryptocurrency matching the provided contract id or symbol is found
        error_message = response['status']['error_message']
        if error_message is not None:
            bot.reply_to(message, f'Could not add coin: {error_message}')
            del user_states[user_id]
            return

        data = response['data']

        if len(data) == 1:
            coin_id = list(data.keys())[0]
            coin_data = data[coin_id]
            coin_symbol = coin_data['symbol']

            # Make sure the coin isn't already in cryptos_json
            for known_coin in cryptos_json:
                if known_coin == coin_symbol:
                    bot.reply_to(message, f'Cannot add coin. {coin_symbol} is already known by the bot.')
                    del user_states[user_id]
                    return

            coin_name = coin_data['name']
            website = coin_data['urls']['website'][0]
            if coin_data['platform'] is not None:
                platform = coin_data['platform']['symbol']
                contract_id = coin_data['platform']['token_address']
            else:
                platform = contract_id = None

            if platform == 'ETH':
                platform = 'ETH ERC-20'
            elif platform == 'BNB':
                platform = 'BNB BEP20'

            cryptos_json_tmp = {coin_symbol: {
                                    "INFO": {
                                        "contract_id": contract_id,
                                        "chain": platform,
                                        "website": website
                                    },
                                    "cmc_id": coin_id,
                                    "cmc_name": coin_name},
                                }

            user_states[user_id].new_crypto_tmp = cryptos_json_tmp
            user_states[user_id].state = 1

            # Prompt the user to confirm the coin's info
            bot_message = (f"-- {contract_id if contract_id else (coin_name)} --\n"
                           f"Name: {coin_name}\n"
                           f"Symbol: {coin_symbol}\n"
                           f"Chain: {platform}\n\n"
                           "Is this correct? (y/n)"
                           )
            bot.send_message(message.chat.id, bot_message)
        else:
            # Got multiple cryptos, have to make the user pick one
            bot_message = ""
            for crypto in data:
                bot_message += (f"-- {crypto['symbol']} --\n"
                                f"Slug: {crypto['name']}\n")
                if platform := crypto['platform']:
                    bot_message += (f"Contract Address: {platform['token_address']}\n"
                                    f"Chain: {platform['symbol']}\n")
                bot_message += '\n'

            bot.send_message(message.chat.id, bot_message)

    elif command_state == 1:
        answer = (message.text if len(message.text.split()) == 1 else '').upper()

        if answer == 'Y':
            # Add the new coin to the cryptos_json dict so that it is usable immediately
            cryptos_json.update(user_states[user_id].new_crypto_tmp)

            # Dump cryptos_json to disk
            with open('cryptos.json', 'r+') as f:
                f.seek(0)
                json.dump(cryptos_json, f, indent=4)

            bot.reply_to(message, 'Success. The new coin has been added to the bot.')
            log_to_disk(f'Added {list(user_states[user_id].new_crypto_tmp.keys())[0]} to the bot',
                        '/new_crypto', message)
        else:
            bot.reply_to(message, 'Aborting command.')

        del user_states[user_id]


def handle_update_crypto(message):
    user_id = message.from_user.id

    # Check if the user is currently using a stated command
    if user_state := user_states.get(user_id):
        return True if user_state.current_command == 'update_crypto' else False

    # See if the user is starting this command
    starting_command = (message.text.split()[0] == '/update_crypto')

    if starting_command and user_id in ADMIN_IDS:
        user_states[user_id] = UserState('update_crypto')
        return True

    return False


@bot.message_handler(func=handle_update_crypto)
def update_crypto(message):
    user_id = message.from_user.id

    command_state = user_states[user_id].state

    if command_state == 0:
        coin_symbol = (message.text.split()[1] if len(message.text.split()) == 2 else '').upper()

        if coin_symbol == '':
            usage_error(message, "/update_crypto COIN_SYMBOL")
            del user_states[user_id]
            return

        if coin_symbol not in cryptos_json:
            bot.reply_to(message, f"Cannot update coin: unknown coin {coin_symbol}")
            return

        user_states[user_id].new_crypto_tmp = [coin_symbol, cryptos_json[coin_symbol]]

        reply = f'--- {coin_symbol} Info ---\n'
        index = 0
        for k, v in cryptos_json[coin_symbol]["INFO"].items():
            reply += f"[{index}] - {k}: {v}\n"
            index += 1

        reply += f"Enter the index of the entry you want to change or enter {index} to add a new entry.\n" +\
                 "Enter anything else to abort."
        user_states[user_id].state = 1

        bot.reply_to(message, reply)
    elif command_state == 1:
        answer = (message.text if len(message.text.split()) == 1 else '')

        current_entries_len = len(user_states[user_id].new_crypto_tmp[1]["INFO"])

        if (not answer.isdigit()) or (int(answer) < 0) or (int(answer) > current_entries_len):
            del user_states[user_id]
            bot.reply_to(message, 'Aborting command.')
            return

        answer = int(answer)

        if current_entries_len == answer:
            # User is making a new entry
            bot.send_message(message.chat.id, "Enter a name for the new entry or enter ABORT to cancel.")
            user_states[user_id].state = 2
        else:
            # User is updating an existing entry
            value_to_change = list(user_states[user_id].new_crypto_tmp[1]["INFO"].keys())[answer]
            bot.send_message(message.chat.id, f"Enter a new value for {value_to_change} or enter ABORT to cancel.")
            user_states[user_id].additional_command_info = value_to_change
            user_states[user_id].state = 3
    elif command_state == 2:
        answer = (message.text if message.text is not None else '')

        if (answer == '') or (answer.upper() == 'ABORT'):
            del user_states[user_id]
            bot.reply_to(message, 'Aborting command.')
            return

        user_states[user_id].additional_command_info = answer
        bot.send_message(message.chat.id, f"Enter a value for {answer}.")
        user_states[user_id].state = 3
    elif command_state == 3:
        answer = (message.text if message.text is not None else '')

        if answer == '' or (answer.upper() == 'ABORT'):
            del user_states[user_id]
            bot.reply_to(message, 'Aborting command.')
            return

        user_states[user_id].new_crypto_tmp[1]['INFO'][user_states[user_id].additional_command_info] = answer

        coin_symbol = user_states[user_id].new_crypto_tmp[0]
        index = 0
        reply = f'--- {coin_symbol} Updated Info ---\n'
        for k, v in cryptos_json[coin_symbol]["INFO"].items():
            reply += f"[{index}] - {k}: {v}\n"
            index += 1
        reply += "\n Is this information correct? (y/n)"

        bot.send_message(message.chat.id, reply)

        user_states[user_id].state = 4
    elif command_state == 4:
        answer = (message.text if len(message.text.split()) == 1 else '').upper()

        if answer == 'Y':
            cryptos_json[user_states[user_id].new_crypto_tmp[0]] = user_states[user_id].new_crypto_tmp[1]

            # Dump cryptos_json to disk
            with open('cryptos.json', 'w') as f:
                json.dump(cryptos_json, f, indent=4)

            bot.reply_to(message, 'Coin successfully updated')
            log_to_disk(f'Updated {user_states[user_id].new_crypto_tmp[0]}', '/update_crypto', message)
        else:
            bot.reply_to(message, 'Aborting command.')

        del user_states[user_id]


def handle_at_everyone(message):
    if message.from_user.id not in ADMIN_IDS \
       or not message.text.startswith('/everyone ') \
       or message.chat.type == "private":
        return False

    return True


@bot.message_handler(func=handle_at_everyone)
@uses_notification_db
def at_everyone(cursor, message):
    chat_id = message.chat.id

    # Get the first name and user ID for all users in this group who are registered for /everyone notifications
    cursor.execute(f'SELECT to_notify FROM at_everyone_notifications WHERE group_chat_id={chat_id}')

    if (result := cursor.fetchone()) is not None:
        # User entries are split up by semicolons
        user_entries = result[0].split(';')

        response = ''
        for user_entry in user_entries:
            # First name and user ID are seperated by a |
            first_name, user_id = user_entry.split('|')

            response += f'[{first_name}](tg://user?id={user_id}) '

        bot.reply_to(message, response, parse_mode='Markdown')


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
        price_notifications.check_price_notifications()
    except Exception as e:
        logger.error("Price checker stopped: %s", type(e).__name__)


price_notifications.initialize_db()
logger.info("Scooty Scout started")

# Workaround to stop the bot from failing when HTTP timeout happens but still allow CTRL-C to close it
telegram_polling_thread = Thread(target=message_polling)
telegram_polling_thread.start()

price_checker_thread = Thread(target=run_price_checker)
price_checker_thread.start()
