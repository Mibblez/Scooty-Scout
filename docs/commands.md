# Command reference

[Return to the README](../README.md).

Discord commands use named options, and Telegram commands use positional
arguments. The examples use SAND from the example catalog. The bot ignores
case in coin symbols.

The bot identifies admins through `DISCORD_ADMIN_IDS` or `ADMIN_IDS` in `.env`.
Each section states which commands require admin access. Everyone can use the
other commands. Discord sends text responses as attachments when they exceed
its message limit.

## Coin information

`/coins` lists all known cryptocurrency symbols. `/price` gets a coin's current
USD price and 24-hour price movement. `/info` shows its saved information and
links. `/ethgas` gets Ethereum gas estimates.

The cryptocurrency must appear in `/coins` before you can use it with `/price`,
`/info`, or `/price_notify`.

Discord:

```text
/coins
/price symbol:SAND
/info symbol:SAND
/ethgas
```

Telegram:

```text
/coins
/price SAND
/info SAND
/ethgas
```

`/info` reads the [coin catalog](#coin-catalog) and skips empty fields. Discord
shows a card with links and the contract address. Telegram sends plainly formatted text.

`/ethgas` uses `ETHERSCAN_API_KEY` from
[Etherscan](https://info.etherscan.com/api-keys/) and the
[Etherscan V2 Gas Oracle](https://docs.etherscan.io/api-reference/endpoint/gasoracle).
It shows Safe, Proposed, and Fast rates in gwei, along with the estimated cost
of a Uniswap swap in USD using 152,000 gas. Actual transaction costs vary. The
Etherscan key is optional for running the bot and enables `/ethgas`.

## Coin management

`/new_crypto` adds a cryptocurrency by symbol or contract address.
`/update_crypto` edits saved information for a known cryptocurrency. Both
commands require admin access.

Discord:

```text
/new_crypto identifier:BTC
/update_crypto symbol:SAND field:website value:https://www.sandbox.game/en/
```

Telegram:

```text
/new_crypto BTC
/update_crypto SAND
```

`/new_crypto` looks up the cryptocurrency in CoinMarketCap and asks to confirm
before saving. The bot rejects symbols it already knows. If a symbol matches
multiple coins, provide a contract address. After confirmation, the bot saves
the entry to `cryptos.json` and makes it available to `/coins`, `/price`, `/info`,
and price notifications.

`/update_crypto` edits fields under `INFO`, including `website`, `chain`, and
`contract_id`. It accepts custom field names and treats field names as case
sensitive.

On Discord, both commands show a private preview with confirmation and
cancellation buttons. Only the user who ran the command can use them, and they
expire after two minutes. If a field changes after its preview, run
`/update_crypto` again to review the current value. Telegram uses chat replies
for confirmation; `/update_crypto` also asks which field to edit. The bot saves
confirmed changes to `cryptos.json`.

## Price alerts

`/price_notify` sets a price notification for a specified cryptocurrency.
`/check_notifications` lists your active notifications, and
`/delete_notification` deletes your notification for a coin.

Discord:

```text
/price_notify symbol:SAND target:0.5
/check_notifications
/delete_notification symbol:SAND
```

Telegram:

```text
/price_notify SAND 0.5
/check_notifications
/delete_notification SAND
```

The target price must be a positive USD amount. Each user can have one
notification per cryptocurrency across the bot's conversations. Setting another
notification for the same coin replaces the previous one.

The target price can be above or below the current price. For a target above the
current price, the bot sends the notification when a check finds a price strictly
above the target. For a target at or below the current price, the bot sends it
when a check finds a price strictly below the target. The bot chooses this
direction when you set the notification.

The bot checks prices every 15 minutes while it runs and sends notifications by
DM. It keeps notifications across restarts, deletes them after successful
delivery, and keeps failed deliveries for the next check. Set a new notification
to receive another one for that coin after delivery.

Discord users need to allow DMs from server members. The bot registers you when
you create a notification. On Telegram, send `/start` to the bot in a private
chat first.

Discord keeps confirmations and notification lists private. Listing and deleting
notifications use only saved data. You can delete your own notification even if
the coin no longer appears in the catalog.

## Group notifications

`/notify_me` adds you to the group notification list, and `/dont_notify_me`
removes you from it. Admins use `/everyone` to send a message that mentions
subscribers.

Discord:

```text
/notify_me
/dont_notify_me
/everyone message:Market update
```

Telegram:

```text
/notify_me
/dont_notify_me
/everyone Market update
```

These commands require a Telegram group or a Discord server channel or thread.
The bot saves a separate subscription list for each conversation. Unsubscribing
in one conversation keeps your subscriptions elsewhere. Group subscriptions
have separate settings from price notifications.

On Discord, subscription confirmations are private. `/everyone`
posts the admin's message and subscriber mentions publicly, then sends the admin
a private confirmation. Messages can contain up to 2,000 characters. The bot
splits large subscriber lists into multiple posts. Each post can ping only the
subscribers in that batch. The bot disables role pings and `@everyone` pings.

If a post fails, the bot stops sending and tells the admin how many subscriber
mentions it sent. Admins control retries.

## Custom media

`/new_media_command` creates a saved image command, and
`/new_twitter_video_command` creates a saved video command. Both require admin
access. Anyone can list saved commands with `/list_commands` or run them.

### Discord

```text
/new_media_command name:party_frog image:ATTACHMENT group:memes
/new_twitter_video_command name:party_video url:PUBLIC_POST_URL group:memes
/list_commands
/list_commands group:memes
/party_frog
/party_video
```

For images, select a PNG, JPEG, GIF, or WebP file in Discord's attachment picker.
For videos, provide a public `twitter.com` or `x.com` post link or copied video
address. Images and videos must be under the the 8 MiB limit. Videos must use MP4.

The bot converts command names and groups to lowercase. Names must contain
1 to 32 letters, numbers, underscores, or hyphens and start with a letter or
number. The bot rejects existing command names, including built-in names.
Built-in and custom commands share a limit of 100 slash commands.

The optional `group` defaults to `user_commands`. The bot creates groups as
needed. `/list_commands` lists all custom commands; its `group` option filters
the list. For an unknown group, the bot lists the available group names.

Twitter/X share links can include query parameters. The downloader uses the first
video unless the URL specifies `/video/NUMBER`. It uses `yt-dlp` and a direct MP4
format, which avoids an ffmpeg dependency. The bot reports an error for posts
that require a login or provide no suitable video.

On Discord, creation replies are private. Saved commands send media in the
conversation where you run them and use the bot's guild or global registration
scope. The bot restores them at startup. Keep the files listed in
[Backups and updates](../README.md#backups-and-updates) when deploying.

Discord's command picker also shows the built-in commands.

### Telegram

Send a photo with this command as its caption:

```text
/new_media_command party_frog
```

The optional final argument selects an existing command file without its `.py`
extension, such as `/new_media_command party_frog memes`. The default file is
`user_commands.py`. Command names can contain letters, digits, and underscores
and must start with a letter or digit.

Create video commands and list saved commands with:

```text
/new_twitter_video_command party_video https://twitter.com/i/status/VIDEO_ID
/list_commands user_commands
/party_frog
/party_video
```

The video command expects a copied `twitter.com/i/status/NUMBER` address and saves
the command in `user_commands.py`. `/list_commands` takes a command file name.
Running it without a name shows the available files.

See the [Telegram caption example](../example_images/new_media_command.png).

## Other commands and aliases

`/wen` sends a random joke reply. It accepts `moon`, `lambo`, or
`aston`. Use `/wen thing:moon` on Discord and `/wen moon` on Telegram.

`/wen moon` can also send audio from `media/wen_moon.ogg`. Discord
sends the file as an attachment, and Telegram sends it as audio. The bot sends
text replies with or without this file.

On Telegram, `/start` registers you for price notifications. Send it in a
private chat. `/dextools` returns the DEXTools homepage link.
Coin-specific support remains unfinished.

Telegram accepts `/pnot` for `/price_notify`, `/cnot` for `/check_notifications`,
`/dnot` for `/delete_notification`, `/nmc` for `/new_media_command`, `/ntv` for
`/new_twitter_video_command`, `/lc` for `/list_commands`, and `/WEN` for `/wen`.

## Coin catalog

The `cryptos.json` file contains all known cryptocurrencies by symbol. Copy
[cryptos_example.json](../cryptos_example.json) for a new installation. The admin
commands update this file. If you edit it manually, restart the bot to load your
changes.

Example catalog:

```json
{
    "SAND": {
        "INFO": {
            "contract_id": "0x3845badAde8e6dFF049820680d1F14bD3903a5d0",
            "chain": "ETH ERC-20",
            "website": "https://www.sandbox.game/en/"
        },
        "cmc_id": "6210",
        "cmc_name": "The Sandbox"
    }
}
```

The `cmc_id` field contains the CoinMarketCap ID as a string, and `cmc_name`
contains the cryptocurrency's display name. The `INFO` dictionary contains the
information that `/info` shows. Native coins can omit `contract_id` and `chain`.

The optional `cmc_slug` field supplies the canonical CoinMarketCap URL slug.
`/new_crypto` saves it automatically. For older entries, the bot lowercases
`cmc_name` and replaces spaces with hyphens when building CoinMarketCap links.
