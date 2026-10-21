"""Translate Discord slash commands and send responses."""

import asyncio
import io
import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, suppress
from typing import Literal

import discord
from discord import app_commands
from discord.ext import tasks

from backend_config import Backend
from bot_application import (
    BotApplication,
    CoinCandidate,
    CoinCreationError,
    CoinInfo,
    CoinInfoError,
    CoinUpdate,
    CoinUpdateError,
)
from bot_utilities import log_to_disk
from command_context import CommandContext
from ethereum_gas import GasPriceError
from group_notifications import GroupNotificationError
from media_commands import MediaCommand, MediaCommandError
from price_alerts import PriceAlertError

logger = logging.getLogger("scooty_scout")


def context_from_interaction(interaction: discord.Interaction) -> CommandContext:
    return CommandContext(
        backend=Backend.DISCORD,
        user_id=str(interaction.user.id),
        conversation_id=str(interaction.channel_id or interaction.user.id),
        display_name=interaction.user.display_name,
    )


async def send_followup_text(
    interaction: discord.Interaction,
    text: str,
    *,
    filename: str,
    attachment_message: str,
    ephemeral: bool = False,
) -> None:
    """Send long responses as UTF-8 attachments."""
    if len(text) <= 2000:
        await interaction.followup.send(text, ephemeral=ephemeral)
    else:
        attachment = discord.File(io.BytesIO(text.encode("utf-8")), filename=filename)
        await interaction.followup.send(attachment_message, file=attachment, ephemeral=ephemeral)


def coin_info_embed(info: CoinInfo) -> discord.Embed | None:
    """Return None when the coin card exceeds Discord's embed limits."""
    embed = discord.Embed(title=info.title, color=discord.Color.blurple())
    for label, value in info.fields:
        if label == "Contract address":
            value = f"`{value}`"
        elif label == "Website" and value.startswith(("https://", "http://")):
            value = f"[Visit website]({value})"
        embed.add_field(name=label, value=value, inline=label in ("Network", "Website"))
    if info.links:
        embed.add_field(name="Links", value=" • ".join(f"[{label}]({url})" for label, url in info.links), inline=False)
    if not embed.fields:
        embed.description = "No additional information available."
    if len(info.title) > 256 or len(embed.fields) > 25 or len(embed) > 6000:
        return None
    if any(len(field.name) > 256 or len(field.value) > 1024 for field in embed.fields):
        return None
    return embed


def group_notification_batches(message: str, user_ids: tuple[str, ...]) -> Iterator[tuple[str, list[discord.Object]]]:
    """Split subscriber mentions to meet Discord's message and mention limits."""
    text = message
    users = []
    for user_id in user_ids:
        mention = f"<@{user_id}>"
        user = discord.Object(id=int(user_id))
        separator = "\n" if not users else " "
        if len(text) + len(separator) + len(mention) > 2000 or len(users) == 100:
            yield text, users
            text, users = mention, [user]
        else:
            text += separator + mention
            users.append(user)
    if users:
        yield text, users


class ConfirmNewCoin(discord.ui.View):
    def __init__(self, application: BotApplication, candidate: CoinCandidate, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.bot_application = application
        self.candidate = candidate
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command creator can confirm this coin.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Add coin", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        try:
            self.bot_application.add_coin(self.candidate)
        except (CoinCreationError, OSError) as error:
            await interaction.response.edit_message(content=str(error), view=None)
            self.stop()
            return
        log_to_disk(f"Added {self.candidate.symbol} to the bot", "/new_crypto", context_from_interaction(interaction))
        await interaction.response.edit_message(
            content=f"Success. {self.candidate.symbol} has been added to the bot.", view=None
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Aborting command.", view=None)
        self.stop()


class ConfirmCoinUpdate(discord.ui.View):
    def __init__(self, application: BotApplication, change: CoinUpdate, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.bot_application = application
        self.change = change
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command creator can confirm this change.", ephemeral=True)
            return False
        if self.is_finished():
            await interaction.response.send_message("This update is no longer active.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Save changes", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.defer()
        try:
            await asyncio.to_thread(self.bot_application.update_coin, self.change)
        except CoinUpdateError as error:
            response = str(error)
        except OSError:
            logger.exception("Discord /update_crypto save failed")
            response = "Could not save the coin information. Try again later."
        else:
            response = f"Success. {self.change.symbol}'s {self.change.field} has been updated."
            log_to_disk(
                f"Updated {self.change.symbol}: {self.change.field}",
                "/update_crypto",
                context_from_interaction(interaction),
            )
        await interaction.edit_original_response(content=response, attachments=[], view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Aborting command.", attachments=[], view=None)


class DiscordAdapter(discord.Client):
    def __init__(self, application: BotApplication, admin_ids: set[int], guild_id: int | None) -> None:
        super().__init__(intents=discord.Intents.default())
        self.bot_application = application
        self.admin_ids = admin_ids
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self._media_command_lock = asyncio.Lock()
        self._register_commands()
        if application.media_commands is not None:
            for command in application.media_commands.commands():
                self._register_media_command(command)

    def _register_commands(self) -> None:
        self._register_information_commands()
        self._register_price_alert_commands()
        self._register_group_notification_commands()
        self._register_coin_management_commands()
        self._register_media_management_commands()

    def _register_information_commands(self) -> None:
        @self.tree.command(name="coins", description="List coins known to the bot")
        async def coins(interaction: discord.Interaction) -> None:
            response = self.bot_application.coins(context_from_interaction(interaction))
            if len(response) <= 2000:
                await interaction.response.send_message(response)
            else:
                attachment = discord.File(io.BytesIO(response.encode("utf-8")), filename="coins.txt")
                await interaction.response.send_message("Known coins are attached.", file=attachment)

        @self.tree.command(name="info", description="Show a coin's website, network, and contract details")
        @app_commands.describe(symbol="Known coin symbol, such as SAND (see /coins)")
        async def info(interaction: discord.Interaction, symbol: str) -> None:
            await interaction.response.defer(thinking=True)
            try:
                coin_info = self.bot_application.info(context_from_interaction(interaction), symbol)
            except CoinInfoError as error:
                response = str(error)
            else:
                embed = coin_info_embed(coin_info)
                if embed is not None:
                    await interaction.followup.send(embed=embed)
                    return
                response = coin_info.as_text()
            await send_followup_text(
                interaction, response, filename="info.txt", attachment_message="Coin information is attached."
            )

        @self.tree.command(name="wen", description="Wen moon, lambo, or aston?")
        @app_commands.describe(thing="What are you waiting for?")
        async def wen(interaction: discord.Interaction, thing: Literal["moon", "lambo", "aston"]) -> None:
            reply = self.bot_application.wen(context_from_interaction(interaction), thing)
            if reply is None:
                await interaction.response.send_message("Choose moon, lambo, or aston.", ephemeral=True)
                return
            await interaction.response.send_message(reply.text)
            if reply.audio_path is not None:
                try:
                    with closing(discord.File(reply.audio_path, filename=reply.audio_path.name)) as audio:
                        await interaction.followup.send(file=audio)
                except OSError, discord.HTTPException:
                    logger.warning("Discord /wen audio could not be sent")

        @self.tree.command(name="price", description="Get a coin's USD price and 24-hour change")
        @app_commands.describe(symbol="Known coin symbol, such as BTC (see /coins)")
        async def price(interaction: discord.Interaction, symbol: str) -> None:
            await interaction.response.defer(thinking=True)
            try:
                response = await asyncio.to_thread(
                    self.bot_application.price, context_from_interaction(interaction), symbol
                )
            except Exception:
                logger.exception("Discord /price lookup failed")
                await interaction.followup.send("Could not get the latest price. Try again later.")
                return
            await send_followup_text(
                interaction, response, filename="price.txt", attachment_message="Price command response is attached."
            )

        @self.tree.command(name="ethgas", description="Show Ethereum gas rates and estimated Uniswap costs in USD")
        async def ethgas(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            try:
                prices = await asyncio.to_thread(self.bot_application.ethgas, context_from_interaction(interaction))
            except GasPriceError as error:
                await interaction.followup.send(str(error))
                return
            except Exception:
                logger.exception("Discord /ethgas lookup failed")
                await interaction.followup.send("Could not get Ethereum gas prices. Try again later.")
                return
            embed = discord.Embed(
                title="Ethereum gas",
                description=f"Estimated Uniswap swap cost • {prices.gas_limit:,} gas",
                color=discord.Color.blurple(),
            )
            for estimate in prices.estimates:
                embed.add_field(name=estimate.label, value=estimate.as_text(), inline=True)
            embed.set_footer(text="Source: Etherscan • Actual transaction costs vary.")
            await interaction.followup.send(embed=embed)

    def _register_price_alert_commands(self) -> None:
        @self.tree.command(name="price_notify", description="DM you when a coin crosses your target USD price")
        @app_commands.describe(symbol="Known coin symbol (see /coins)", target="Target price in USD")
        async def price_notify(interaction: discord.Interaction, symbol: str, target: float) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                response = await asyncio.to_thread(
                    self.bot_application.price_notify, context_from_interaction(interaction), symbol, target
                )
            except PriceAlertError as error:
                response = str(error)
            except Exception:
                logger.exception("Discord /price_notify failed")
                response = "Could not set that price notification. Try again later."
            else:
                response += (
                    "\nAlerts arrive by DM. Allow DMs from this server's members. Prices are checked every 15 minutes."
                )
            await send_followup_text(
                interaction,
                response,
                filename="notification.txt",
                attachment_message="Price notification response is attached.",
                ephemeral=True,
            )

        @self.tree.command(name="check_notifications", description="List your active price notifications")
        async def check_notifications(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                response = await asyncio.to_thread(
                    self.bot_application.check_notifications, context_from_interaction(interaction)
                )
            except PriceAlertError as error:
                response = str(error)
            except Exception:
                logger.exception("Discord /check_notifications failed")
                response = "Could not check price notifications. Try again later."
            await send_followup_text(
                interaction,
                response,
                filename="notifications.txt",
                attachment_message="Price notifications are attached.",
                ephemeral=True,
            )

        @self.tree.command(name="delete_notification", description="Delete one of your price notifications")
        @app_commands.describe(symbol="Coin symbol for the notification to delete")
        async def delete_notification(interaction: discord.Interaction, symbol: str) -> None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                response = await asyncio.to_thread(
                    self.bot_application.delete_notification, context_from_interaction(interaction), symbol
                )
            except PriceAlertError as error:
                response = str(error)
            except Exception:
                logger.exception("Discord /delete_notification failed")
                response = "Could not delete that price notification. Try again later."
            await send_followup_text(
                interaction,
                response,
                filename="notification.txt",
                attachment_message="Price notification response is attached.",
                ephemeral=True,
            )

    def _register_group_notification_commands(self) -> None:
        @self.tree.command(name="notify_me", description="Opt into this channel's /everyone notifications")
        @app_commands.guild_only()
        async def notify_me(interaction: discord.Interaction) -> None:
            await self._update_group_subscription(interaction, self.bot_application.notify_me)

        @self.tree.command(name="dont_notify_me", description="Opt out of this channel's /everyone notifications")
        @app_commands.guild_only()
        async def dont_notify_me(interaction: discord.Interaction) -> None:
            await self._update_group_subscription(interaction, self.bot_application.dont_notify_me)

        @self.tree.command(name="everyone", description="Notify this channel's subscribed users (admin only)")
        @app_commands.guild_only()
        @app_commands.describe(message="Message to send with the subscriber mentions")
        async def everyone(interaction: discord.Interaction, message: app_commands.Range[str, 1, 2000]) -> None:
            if interaction.user.id not in self.admin_ids:
                await interaction.response.send_message("Only admins can send group notifications.", ephemeral=True)
                return
            if interaction.guild_id is None or interaction.channel is None:
                await interaction.response.send_message(
                    "Use this command in a server channel or thread.", ephemeral=True
                )
                return
            message = message.strip()
            if not message or len(message) > 2000:
                await interaction.response.send_message("Provide a message of 1 to 2,000 characters.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                subscribers = await asyncio.to_thread(
                    self.bot_application.group_subscribers, context_from_interaction(interaction)
                )
            except GroupNotificationError as error:
                response = str(error)
            except sqlite3.Error:
                logger.exception("Discord /everyone subscriber lookup failed")
                response = "Could not load group notification subscribers. Try again later."
            else:
                if not subscribers:
                    await interaction.followup.send(
                        "No one has subscribed here yet. Use /notify_me to opt in.", ephemeral=True
                    )
                    return
                sent = 0
                try:
                    for text, users in group_notification_batches(message, subscribers):
                        await interaction.channel.send(
                            text,
                            allowed_mentions=discord.AllowedMentions(
                                everyone=False, roles=False, users=users, replied_user=False
                            ),
                        )
                        sent += len(users)
                except discord.HTTPException:
                    logger.exception("Discord /everyone delivery failed")
                    response = (
                        f"Could not send all group notifications; {sent} subscriber mentions were sent. "
                        "Check the bot's permission to send messages here."
                    )
                else:
                    response = f"Mentioned {sent} subscribed users here."
                    log_to_disk(response, "/everyone", context_from_interaction(interaction))
            await interaction.followup.send(response, ephemeral=True)

    def _register_coin_management_commands(self) -> None:
        @self.tree.command(name="new_crypto", description="Add a cryptocurrency to the bot")
        @app_commands.describe(identifier="Coin symbol or contract address")
        async def new_crypto(interaction: discord.Interaction, identifier: str) -> None:
            if interaction.user.id not in self.admin_ids:
                await interaction.response.send_message("Only admins can add coins.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                candidate = await asyncio.to_thread(self.bot_application.prepare_new_coin, identifier)
            except CoinCreationError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            except Exception:
                logger.exception("Discord /new_crypto lookup failed")
                await interaction.followup.send("Could not look up that coin. Try again later.", ephemeral=True)
                return
            view = ConfirmNewCoin(self.bot_application, candidate, interaction.user.id)
            await interaction.followup.send(f"{candidate.preview()}\n\nAdd this coin?", view=view, ephemeral=True)

        @self.tree.command(name="update_crypto", description="Update or add a saved metadata field for a coin")
        @app_commands.describe(
            symbol="Known coin symbol (see /coins)",
            field="Metadata key: website, chain, contract_id, or a custom field name",
            value="New value for this metadata field",
        )
        async def update_crypto(interaction: discord.Interaction, symbol: str, field: str, value: str) -> None:
            if interaction.user.id not in self.admin_ids:
                await interaction.response.send_message("Only admins can update coins.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                change = self.bot_application.prepare_coin_update(symbol, field, value)
            except CoinUpdateError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            view = ConfirmCoinUpdate(self.bot_application, change, interaction.user.id)
            preview = f"{change.preview()}\n\nSave this change?"
            if len(preview) <= 2000:
                await interaction.followup.send(preview, view=view, ephemeral=True)
            else:
                attachment = discord.File(io.BytesIO(preview.encode("utf-8")), filename="update_crypto.txt")
                await interaction.followup.send(
                    "Review the attached change, then choose Save changes or Cancel.",
                    file=attachment,
                    view=view,
                    ephemeral=True,
                )

    def _register_media_management_commands(self) -> None:
        @self.tree.command(name="new_media_command", description="Create a slash command that sends an uploaded image")
        @app_commands.describe(
            name="New command name, such as party_frog",
            image="PNG, JPEG, GIF, or WebP image, up to 8 MiB",
            group="Command group for /list_commands (default: user_commands)",
        )
        async def new_media_command(
            interaction: discord.Interaction, name: str, image: discord.Attachment, group: str = "user_commands"
        ) -> None:
            if interaction.user.id not in self.admin_ids:
                await interaction.response.send_message("Only admins can create media commands.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            async with self._media_command_lock:
                try:
                    command = self.bot_application.prepare_media_command(name, image.filename, group, image.size)
                    self._check_media_command(command)
                    if image.content_type and not image.content_type.startswith("image/"):
                        raise MediaCommandError("Attach a PNG, JPEG, GIF, or WebP image.")
                    content = await image.read()
                    await asyncio.to_thread(self.bot_application.add_media_command, command, content)
                except MediaCommandError as error:
                    await interaction.followup.send(str(error), ephemeral=True)
                    return
                except OSError, discord.HTTPException:
                    logger.exception("Discord /new_media_command upload or save failed")
                    await interaction.followup.send("Could not save the image. Try again later.", ephemeral=True)
                    return
                await self._publish_media_command(interaction, command, "/new_media_command")

        @self.tree.command(
            name="new_twitter_video_command", description="Create a slash command from a Twitter/X video"
        )
        @app_commands.describe(
            name="New command name, such as party_video",
            url="Public Twitter/X post or copied video address",
            group="Command group for /list_commands (default: user_commands)",
        )
        async def new_twitter_video_command(
            interaction: discord.Interaction, name: str, url: str, group: str = "user_commands"
        ) -> None:
            if interaction.user.id not in self.admin_ids:
                await interaction.response.send_message("Only admins can create media commands.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            async with self._media_command_lock:
                try:
                    command = self.bot_application.prepare_twitter_video_command(name, group)
                    self._check_media_command(command)
                    await asyncio.to_thread(self.bot_application.add_twitter_video_command, command, url)
                except MediaCommandError as error:
                    await interaction.followup.send(str(error), ephemeral=True)
                    return
                except OSError:
                    logger.exception("Discord /new_twitter_video_command save failed")
                    await interaction.followup.send("Could not save the video. Try again later.", ephemeral=True)
                    return
                await self._publish_media_command(interaction, command, "/new_twitter_video_command")

        @self.tree.command(name="list_commands", description="List saved custom media commands, optionally by group")
        @app_commands.describe(group="Show only this command group; omit to list all groups")
        async def list_commands(interaction: discord.Interaction, group: str | None = None) -> None:
            await interaction.response.defer(thinking=True)
            try:
                response = self.bot_application.list_commands(context_from_interaction(interaction), group)
            except MediaCommandError as error:
                response = str(error)
            await send_followup_text(
                interaction, response, filename="commands.txt", attachment_message="Custom commands are attached."
            )

    async def _update_group_subscription(
        self, interaction: discord.Interaction, update: Callable[[CommandContext], str]
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Use this command in a server channel or thread.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            response = await asyncio.to_thread(update, context_from_interaction(interaction))
        except GroupNotificationError as error:
            response = str(error)
        except sqlite3.Error:
            logger.exception("Discord group notification preference update failed")
            response = "Could not save your group notification preference. Try again later."
        await interaction.followup.send(response, ephemeral=True)

    def _check_media_command(self, command: MediaCommand) -> None:
        if self.tree.get_command(command.name) is not None:
            raise MediaCommandError(f"Cannot create /{command.name}. Command already exists.")
        if len(self.tree.get_commands()) >= 100:
            raise MediaCommandError("The bot has reached Discord's limit of 100 slash commands.")

    async def _publish_media_command(
        self, interaction: discord.Interaction, command: MediaCommand, source_command: str
    ) -> None:
        self._register_media_command(command)
        log_to_disk(f"Created /{command.name}", source_command, context_from_interaction(interaction))
        try:
            await self._sync_commands()
        except discord.HTTPException:
            logger.exception("Discord media command sync failed")
            response = f"Saved /{command.name}, but Discord could not refresh its commands. Restart the bot to retry."
        else:
            response = f"Created /{command.name}. Use it to send the saved {command.media_type}."
        await interaction.followup.send(response, ephemeral=True)

    def _register_media_command(self, command: MediaCommand) -> None:
        if self.tree.get_command(command.name) is not None:
            raise MediaCommandError(f"Saved media command /{command.name} conflicts with a built-in command.")
        directory = self.bot_application.media_commands.directory

        async def send_media(interaction: discord.Interaction) -> None:
            await interaction.response.defer(thinking=True)
            try:
                with closing(discord.File(directory / command.filename, filename=command.filename)) as attachment:
                    await interaction.followup.send(file=attachment)
            except OSError, discord.HTTPException:
                logger.exception("Discord media command /%s failed", command.name)
                await interaction.followup.send(
                    f"Could not send the saved {command.media_type}. Ask an admin to check its file."
                )

        self.tree.add_command(
            app_commands.Command(
                name=command.name,
                description=f"Send the saved {command.media_type} for {command.name}",
                callback=send_media,
            )
        )

    async def _sync_commands(self) -> None:
        if self.guild_id is None:
            await self.tree.sync()
        else:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

    async def setup_hook(self) -> None:
        await self._sync_commands()
        if self.bot_application.price_alerts is not None:
            self.check_price_notifications.start()

    @tasks.loop(minutes=15)
    async def check_price_notifications(self) -> None:
        alerts = self.bot_application.price_alerts
        if alerts is None:
            return
        try:
            notifications = await asyncio.to_thread(alerts.due_notifications)
        except Exception:
            logger.exception("Discord price notification check failed")
            return
        for notification in notifications:
            try:
                user = self.get_user(notification.user_id) or await self.fetch_user(notification.user_id)
                # Recheck after the recipient lookup in case the user canceled or replaced the alert.
                if not await asyncio.to_thread(alerts.is_pending, notification.notification_id):
                    continue
                await user.send(notification.message())
                await asyncio.to_thread(alerts.acknowledge, notification.notification_id)
            except discord.HTTPException:
                logger.warning(
                    "Could not DM Discord user %s; retaining price notification %s for retry",
                    notification.user_id,
                    notification.notification_id,
                )
            except Exception:
                logger.exception("Discord price notification %s failed", notification.notification_id)

    @check_price_notifications.before_loop
    async def before_price_notifications(self) -> None:
        await self.wait_until_ready()

    async def close(self) -> None:
        task = self.check_price_notifications.get_task()
        self.check_price_notifications.cancel()
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
        await super().close()
