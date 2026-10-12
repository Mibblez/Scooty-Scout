import json
import logging
from collections.abc import Iterable
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects

from command_context import CommandContext


logger = logging.getLogger("scooty_scout")


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
        logger.warning("Video download warning: %s", msg)

    def error(self, msg):
        logger.error("Video download error: %s", msg)


def usage_error(usage_str: str = '') -> str:
    return f'Usage\n{usage_str}'


def unknown_coin(invalid_coin_str: object, known_coins: Iterable[str]) -> str:
    return (f"Unknown coin: {invalid_coin_str}\n\nKnown coins:"
            f"{' ; '.join(known_coins)}")


def log_to_disk(log_message, command_name, actor: CommandContext | None = None):
    """Record an admin change, including the actor when one is available."""
    if actor is not None:
        log_message = f'{{{actor.display_name} - {actor.user_id}}} {log_message}'

    logger.info("(%s)%s", command_name, log_message)


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
        logger.warning("CoinMarketCap quote request failed: %s", type(e).__name__)
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
        logger.warning("CoinMarketCap info request failed: %s", type(e).__name__)
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
        logger.warning("CoinMarketCap map request failed: %s", type(e).__name__)
        return None
