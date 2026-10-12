import json
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
from datetime import datetime

import globals


class UserState:
    def __init__(self, current_command: str) -> None:
        self.__current_command = current_command
        self.state = 0
        self.new_crypto_tmp = None
        self.additional_info = None

    def __repr__(self) -> str:
        return f"{self.__current_command}-{self.state}"

    @property
    def current_command(self):
        return self.__current_command


class TwitterVideoLogger(object):
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def usage_error(message, usage_str: str = ''):
    globals.bot.send_message(message.chat.id, f'Usage\n{usage_str}')


def unknown_coin(message, invalid_coin_str):
    globals.bot.send_message(message.chat.id,
                             f"Unknown coin: {invalid_coin_str}\n\nKnown coins:"
                             f"{' ; '.join([x for x in globals.cryptos_json.keys()])}")


def log_to_disk(log_message, command_name, user_message=None):
    # Append user's name and ID to the start of the log file, if provided via user_message
    if user_message is not None:
        user_id = user_message.from_user.id
        user_first_name = user_message.from_user.first_name
        user_last_name = user_message.from_user.last_name
        log_message = f'{{{user_first_name} {user_last_name} - {user_id}}} {log_message}'

    with globals.log_lock:
        with open('botlog.log', 'a') as log_file:
            time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            log_file.write(f'[{time_now}]({command_name}){log_message}\n')


def get_coin_data(coin_id, cmc_api_key):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': cmc_api_key,
    }

    parameters = {
        'id': coin_id
    }

    session = Session()
    session.headers.update(headers)

    try:
        response = session.get(url, params=parameters)
        data = json.loads(response.text)
        return data
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        print(e)
        return None


#FIXME: Make contract_address and id optional args
def get_coin_info(contract_address, cmc_api_key, id=None):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/info'
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': cmc_api_key,
    }

    if id is None:
        parameters = {
            'address': contract_address
        }
    else:
        parameters = {
            'id': id
        }

    session = Session()
    session.headers.update(headers)

    try:
        response = session.get(url, params=parameters)
        data = json.loads(response.text)
        return data
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        print(e)
        return None


def cmc_id_map(symbol, cmc_api_key):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/map'
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': cmc_api_key,
    }

    parameters = {
        'symbol': symbol,
    }

    session = Session()
    session.headers.update(headers)

    try:
        response = session.get(url, params=parameters)
        data = json.loads(response.text)
        return data
    except (ConnectionError, Timeout, TooManyRedirects) as e:
        print(e)
        return None
