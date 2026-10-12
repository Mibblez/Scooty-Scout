global bot, cryptos_json, CMC_API_KEY


def initilize(telebot, cryptos_json_other, cmc_api_key):
    global bot, cryptos_json, CMC_API_KEY
    bot = telebot
    cryptos_json = cryptos_json_other
    CMC_API_KEY = cmc_api_key
