"""Discord slash commands and interaction translation."""

import asyncio
import io
import logging

import discord
from discord import app_commands

from backend_config import Backend
from bot_application import BotApplication, CoinCandidate, CoinCreationError
from bot_utilities import log_to_disk
from command_context import CommandContext

logger = logging.getLogger("scooty_scout")


def context_from_interaction(interaction: discord.Interaction) -> CommandContext:
    return CommandContext(
        backend=Backend.DISCORD,
        user_id=str(interaction.user.id),
        conversation_id=str(interaction.channel_id or interaction.user.id),
        display_name=interaction.user.display_name,
    )


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
        log_to_disk(f"Added {self.candidate.symbol} to the bot", "/new_crypto",
                    context_from_interaction(interaction))
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
            await interaction.followup.send(
                f"{candidate.preview()}\n\nAdd this coin?", view=view, ephemeral=True
            )

    async def setup_hook(self) -> None:
        if self.guild_id is None:
            await self.tree.sync()
        else:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
