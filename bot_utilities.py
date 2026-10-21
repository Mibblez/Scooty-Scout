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


class TwitterVideoLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        logger.warning("Video download warning: %s", msg)

    def error(self, msg):
        logger.error("Video download error: %s", msg)


def usage_error(usage_str: str = "") -> str:
    return f"Usage\n{usage_str}"


def unknown_coin(invalid_coin_str: object, known_coins: Iterable[str]) -> str:
    return f"Unknown coin: {invalid_coin_str}\n\nKnown coins:{' ; '.join(known_coins)}"


def log_to_disk(log_message, command_name, actor: CommandContext | None = None):
    if actor is not None:
        log_message = f"{{{actor.display_name} - {actor.user_id}}} {log_message}"

    logger.info("(%s)%s", command_name, log_message)


def _get_cmc_data(endpoint, parameters, cmc_api_key):
    try:
        with Session() as session:
            session.headers.update(
                {
                    "Accepts": "application/json",
                    "X-CMC_PRO_API_KEY": cmc_api_key,
                }
            )
            response = session.get(
                f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/{endpoint}", params=parameters, timeout=15
            )
            return json.loads(response.text)
    except (ConnectionError, Timeout, TooManyRedirects) as error:
        logger.warning("CoinMarketCap %s request failed: %s", endpoint, type(error).__name__)
        return None


def get_coin_data(coin_id, cmc_api_key):
    return _get_cmc_data("quotes/latest", {"id": coin_id}, cmc_api_key)


def get_coin_info(contract_address, cmc_api_key, id=None):
    parameters = {"address": contract_address} if id is None else {"id": id}
    return _get_cmc_data("info", parameters, cmc_api_key)


def cmc_id_map(symbol, cmc_api_key):
    return _get_cmc_data("map", {"symbol": symbol}, cmc_api_key)
