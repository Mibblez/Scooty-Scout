"""Discord slash commands and interaction translation."""

import asyncio
import io
import logging
from contextlib import suppress

import discord
from discord import app_commands
from discord.ext import tasks

from backend_config import Backend
from bot_application import BotApplication, CoinCandidate, CoinCreationError, CoinInfo, CoinInfoError
from bot_utilities import log_to_disk
from command_context import CommandContext
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
    """Send a deferred reply as text or a UTF-8 attachment when it is too long."""
    if len(text) <= 2000:
        await interaction.followup.send(text, ephemeral=ephemeral)
    else:
        attachment = discord.File(io.BytesIO(text.encode("utf-8")), filename=filename)
        await interaction.followup.send(attachment_message, file=attachment, ephemeral=ephemeral)


def coin_info_embed(info: CoinInfo) -> discord.Embed | None:
    """Build a coin card, falling back to text if it exceeds Discord's embed limits."""
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


class DiscordAdapter(discord.Client):
    def __init__(self, application: BotApplication, admin_ids: set[int], guild_id: int | None) -> None:
        super().__init__(intents=discord.Intents.default())
        self.bot_application = application
        self.admin_ids = admin_ids
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    def _register_commands(self) -> None:
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

    async def setup_hook(self) -> None:
        if self.guild_id is None:
            await self.tree.sync()
        else:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
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
                # The alert may have been canceled while fetching the recipient.
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
