# Scooty Scout

Scooty Scout is a cryptocurrency tracker bot for Discord and Telegram. It
provides coin information, price notifications by DM, group notifications, and
saved image and video commands.

The bot runs one platform per process. Discord uses native slash commands, and
Telegram uses text commands.

## Setup

The bot requires Python 3.14.x, a bot token for your chosen platform, and a
[CoinMarketCap API key](https://coinmarketcap.com/api/).

Clone the repository and open its directory:

```sh
git https://github.com/Mibblez/Scooty-Scout.git
cd Scooty-Scout
```

Create and activate a virtual environment. On Windows, use PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux, use bash or zsh:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```sh
python -m pip install -r requirements.txt
```

For a new installation, copy [cryptos_example.json](cryptos_example.json) to
`cryptos.json`. The example contains BNB and SAND.

## Configuration

The `.env` file contains the API keys and admin IDs for your chosen platform.
Create it in the project directory using an example below, then replace the keys
and IDs with your values. `BOT_BACKEND` selects the platform and defaults to
`telegram` if you leave it out.

### Discord

Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
On its Bot page, select Reset Token to obtain the token.

On Installation, enable Guild Install and select the `bot` and
`applications.commands` scopes. Grant View Channels, Send Messages, Embed Links,
and Attach Files. Grant Send Messages in Threads if you will use threads. Open
the install link to add the bot to your server.
[Discord's setup guide](https://docs.discord.com/developers/quick-start/getting-started)
covers installation.

Enable Developer Mode in Discord. Copy your user ID for the admin list and your
server ID for command registration. Follow
[Discord's ID instructions](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID)
to find them.

```dotenv
BOT_BACKEND=discord
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN
DISCORD_ADMIN_IDS=[123456789012345678]
COINMARKETCAP_API_KEY=YOUR_CMC_KEY

# Optional: register commands in this server for testing
DISCORD_GUILD_ID=987654321098765432
```

The bot uses `DISCORD_ADMIN_IDS` to identify users who can run admin commands.
This setting requires a nonempty list of numeric user IDs, separated by commas.

Set the optional `DISCORD_GUILD_ID` to your server ID to register commands there
for testing. The bot registers commands globally when you leave this setting
out. Refresh Discord when testing new global commands. See
[Discord's registration behavior](https://docs.discord.com/developers/interactions/application-commands#making-a-global-command).

### Telegram

Send `/newbot` to [@BotFather](https://t.me/BotFather) and follow its instructions
to obtain a token. [Telegram's token guide](https://core.telegram.org/bots/tutorial#obtain-your-bot-token)
explains the process.

You can find your numeric Telegram user ID with a bot such as
[@getmyid_bot](https://t.me/getmyid_bot). Add this ID to `ADMIN_IDS` to designate
yourself as an admin. Separate additional admin IDs with commas.

```dotenv
BOT_BACKEND=telegram
TELEGRAM_API_KEY=YOUR_BOT_TOKEN
ADMIN_IDS=[123456789]
COINMARKETCAP_API_KEY=YOUR_CMC_KEY
```

Add the bot to a Telegram group to use group notifications there.

### Ethereum gas (optional)

The `/ethgas` command requires an
[Etherscan API key](https://info.etherscan.com/api-keys/) in `.env`. This setting
works with either platform:

```dotenv
ETHERSCAN_API_KEY=YOUR_ETHERSCAN_KEY
```

## Running

Start the bot from the project directory with the virtual environment active:

```sh
python main.py
```

On Discord, try `/coins`, `/price symbol:SAND`, and `/info symbol:SAND`.

On Telegram, send `/start` to the bot in a private chat, then try `/coins`,
`/price SAND`, and `/info SAND`. Telegram requires `/start` before you set price
notifications. Discord registers you when you create a notification.

With the example catalog, `/coins` lists BNB and SAND. `/price` returns the current
USD price and 24-hour change.

The bot must stay running to receive commands and send notifications.
Activate the virtual environment when opening a new terminal, and restart the
bot after configuration changes or updates. Discord registers slash commands
at startup.

## Commands

The [command reference](docs/commands.md) covers syntax, examples, permissions,
and limits for each command.

The `/coins`, `/price`, `/info`, and `/ethgas` commands provide coin information
and Ethereum gas estimates.

`/price_notify` sets a price notification. `/check_notifications` lists your
active notifications, and `/delete_notification` removes one. The bot checks
prices every 15 minutes and sends notifications by DM. Discord users need to
allow DMs from server members to receive them.

`/notify_me` and `/dont_notify_me` manage group subscriptions. Subscriptions apply
to the current Telegram group or Discord channel or thread. Admins use
`/everyone` to mention subscribers there.

Admins can add cryptocurrencies with `/new_crypto` and edit saved information
with `/update_crypto`. They can create image commands with `/new_media_command`
and video commands with `/new_twitter_video_command`. Anyone can use
`/list_commands` and run saved media commands.

`/wen` sends joke replies. Telegram also has `/start` for price
notification registration and `/dextools` for the DEXTools homepage.
Coin-specific `/dextools` support remains unfinished.

## Backups and updates

Stop the bot before backing up or moving its data. Keep `.env` and `cryptos.json`.

For Discord, back up `discord_notifications.db` and `media/discord/`. The media
directory contains `commands.json` and the saved images and videos.

For Telegram, back up `notifications.db`, `misc_commands/`, and `media/user_media/`.
Also keep `media/wen_moon.ogg` if you added audio for `/wen moon`.

Each platform stores its users, price notifications, and group subscriptions in
its own database, which the bot creates at startup. Custom commands also stay
separate for each platform. Git excludes these data files, `.env`, and
`cryptos.json`, so keep them when updating or redeploying.

To update, stop the bot, back up its data, update your checkout, activate the
virtual environment, reinstall `requirements.txt`, and run `python main.py`.

The bot writes logs to the terminal and `botlog.log`. It rotates the file at
10 MB and keeps three backups. Admin log entries include the actor's name and
platform user ID.

## Troubleshooting

Read the terminal output and `botlog.log` for the error.

If startup fails, run from the project directory. Check `.env`, the selected
platform's admin ID list, and `cryptos.json`.

If PowerShell blocks activation, run the install and startup commands with
`.\.venv\Scripts\python.exe`.
[Python's venv guide](https://docs.python.org/3.14/library/venv.html#how-venvs-work)
covers direct invocation.

If Discord commands are missing, restart the bot. Check the server ID,
installation scopes, and channel permissions. Refresh Discord when testing new
global commands.

If the bot rejects an admin command, check your numeric user ID in the selected
platform's admin list and restart the bot.

If price or coin lookups fail, check `COINMARKETCAP_API_KEY` and network access.

If price notifications fail to arrive, keep the bot running through a scheduled
check. Allow Discord DMs or send Telegram `/start` privately.

If Discord fails to register a saved media command, restart the bot to retry.
The bot keeps the saved command and media.

The [command reference](docs/commands.md) covers video requirements and group
notification scope.

## Development

In the active virtual environment, install development dependencies and run:

```sh
python -m pip install -r requirements-dev.txt
python -m black .
python -m pytest
```

Black uses a 120-character line length from `pyproject.toml`. Use
`python -m black --check .` to check formatting. Pytest reports coverage.
Tests mock network requests and platform interactions. Use a test server or group
to check the command examples against live services.
