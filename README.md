# Scooty Scout

## Crypto Market and Price Alert Bot

Scooty Scout supports Telegram and Discord backends for cryptocurrency information.
Discord command coverage is being added incrementally; `/coins` and `/new_crypto` are available now.

# Table of Contents

* [Setup](#setup)
    * [Python Version](#python-version)
    * [Backend Selection](#backend-selection)
    * [Tests](#tests)
    * [Logging](#logging)
    * [Environment File](#environment-file)
    * [Cryptocurrency JSON File](#cryptocurrency-json-file)
    * [Telegram Bot Setup](#telegram-bot-setup)
    * [Discord Bot Setup](#discord-bot-setup)
* [General Commands](#general-commands)
* [Price Notification Commands](#price-notification-commands)
* [Misc Commands](#misc-commands)

# Setup

## Python Version

This project uses Python 3.14.x (tested with Python 3.14.8). Install the dependencies with:

```sh
python -m pip install -r requirements.txt
```

## Backend Selection

Start the bot with `python main.py`. `BOT_BACKEND` selects which chat platform to
run and defaults to `telegram`, preserving existing deployments. Run one backend
per process. Discord has its own token and admin IDs.

## Tests

Install the development and runtime dependencies, then run the test suite with coverage:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Logging

Scooty Scout writes startup events, failures, and admin changes to the terminal and
`botlog.log`. Command creation entries include the creator's name and Telegram user ID.
The file rotates at 10 MB and keeps three older copies (`botlog.log.1` through `.3`).
API keys are not included in log messages.

## Environment File

`.env` contains the API keys needed by the selected backend.
This file is not included in the project. You will need to make it yourself.

- Telegram: https://core.telegram.org/api/obtaining_api_id
- CoinMarketCap: https://coinmarketcap.com/api/
- Etherscan: https://info.etherscan.com/api-keys/

Telegram users can obtain their user ID from this [bot](https://botostore.com/c/getmyid_bot/). This ID is used to designate admins.

### Sample .env

```.env
TELEGRAM_API_KEY = XXXXXX
COINMARKETCAP_API_KEY = XXXXXX
ETHERSCAN_API_KEY = XXXXXX

ADMIN_IDS = [1, 2, 3]
```

For Discord, use this configuration instead of the Telegram variables:

```.env
BOT_BACKEND=discord
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
DISCORD_ADMIN_IDS=[YOUR_DISCORD_USER_ID]
DISCORD_GUILD_ID=YOUR_TEST_SERVER_ID
COINMARKETCAP_API_KEY=YOUR_CMC_KEY
```

`DISCORD_GUILD_ID` is optional. Setting it registers slash commands in that
server for testing. Only users in `DISCORD_ADMIN_IDS` can use `/new_crypto`.

## Cryptocurrency JSON File

### cryptos.json format
```json
"COIN_SYMBOL": {
    "INFO": {
        "contract_id": "0xCONTRACT_ID",
        "chain": "CHAIN",
        "website": "WEBSITE"
    },
    "cmc_id": "1234",
    "cmc_name": "COIN NAME"
}
```

The `cryptos.json` file contains entries for all cryptocurrencies known to the bot. Each cryptocurrency is referenced by its coin symbol. The `"INFO"` dictionary contains information that is printed out when a user uses the `/info` command. If adding a cryptocurrency manually, [CoinIdFinder](https://coin-id-finder.vercel.app/) can be used to find its CoinMarketCap ID. The `"contract_id"` and `"chain"` fields within `"INFO"` should be excluded for cryptocurrencies that are standalone (such as Binance Coin or Solana). An example crypto.json file can be found under the name [cryptos_example.json](cryptos_example.json).

## Telegram Bot Setup

In order to receive your Telegram API key and to setup the bot itself, you will need to message the [BotFather](https://botostore.com/c/botfather/) and use the `/newbot` command to create a bot. The BotFather can also be used to set a profile picture for the bot along with other things

## Discord Bot Setup

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications). Copy the bot token into `DISCORD_BOT_TOKEN`.
2. Install the application in a test server with the `bot` and `applications.commands` scopes and permission to send messages. Enable Developer Mode in Discord to copy your user ID and the test server ID.
3. Copy `cryptos_example.json` to `cryptos.json`, configure the Discord `.env` values above, install `requirements.txt`, and run `python main.py`.
4. In that server, try `/coins`. As a configured admin, try `/new_crypto` with a coin symbol or contract address. Review the preview and select **Add coin** or **Cancel**. Confirm that `/coins` lists the new symbol and `cryptos.json` contains it.

# General Commands

## New Cryptocurrency (Admin only)

Enters a new cryptocurrency into the bot. The contract ID this command requires can be found by visiting [CoinMarketCap](https://coinmarketcap.com/) and searching for the cryptocurrency. Once a cryptocurrency has been added to the bot, all commands that interact with cryptocurrencies will work (`/price`, `/price_notify`, etc.).

### Usage

```
/new_crypto CONTRACT_ID
```

## Update Cryptocurrency (Admin only)

Updates into for a cryptocurrency that is known to the bot.

### Usage

```
/update_crypto COIN_SYMBOL
```

## Price

Gets the price of the specified cryptocurrency and displays 24H price movement. The specified cryptocurrency must be found in `cryptos.json`.

### Usage 

```
/price COIN_SYMBOL
```

### Example
```
/price BTC

BTC Price: $48,992.267342
⬇️ -6.23% (24H)
```

## Info

Prints all fields under a cryptocurrency's `INFO` field in `cryptos.json`.

### Usage
```
/info COIN_SYMBOL
```

### Example
```
/info SAND

contract_id: 0x3845badAde8e6dFF049820680d1F14bD3903a5d0
chain: ETH ERC-20
website: https://www.sandbox.game/en/
```

## Ethereum Gas

Gets the current gas price for Ethereum in gwei and shows the cost of a Uniswap transfer in USD.

### Usage

```
/ethgas
```

### Example
```
/ethgas

Uniswap Gas (152,000 gas limit)
Safe: 109 gwei ($68.0022)
Proposed: 110 gwei ($68.6261)
Fast: 112 gwei ($69.8738)
```

# Price Notification Commands

## Set Price Notification

Sets a price notification for a specified cryptocurrency. The provided price can be above or below the current price of a cryptocurrency. Users can only have one price notification set per cryptocurrency. If a user sets a price notification for a cryptocurrency that they already have a notification for, the old notification will be overridden. Prices are checked once every 15 minutes. The specified cryptocurrency must be found in `cryptos.json`.

The data for price_notifications is stored in a SQLite database named `notifications.db`. This file is created on bot startup if it does not exist already.

### Usage

```
/price_notify COIN_SYMBOL NOTIFICATION_PRICE
```

## Delete Price Notification

Deletes an active notification that the user has set.

### Usage

```
/delete_notification COIN_SYMBOL
```

## Check Price Notifications

Prints out all active notifications the user has set.

### Usage

```
/check_notifications
```

# Misc Commands

## New Media Command (Admin Only)

Creates a new command with a specified name. This command requires a user to attach an image that will be used for the new command.

## Usage
```
/new_media_command COMMAND_NAME
```

### Example

<img src="./example_images/new_media_command.png" alt="new_media_command_example" width="400">

## List Commands

Gives a list of available commands in a specified file. Useful if users make a lot of commands using `/new_media_command`.

### Usage

```
/list_commands FILE_NAME
```

## wen

Joke command. Accepted arguments are "moon", "lambo", or "aston".

### Usage

```
/wen THING
```
