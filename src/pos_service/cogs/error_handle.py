import traceback
from logging import getLogger

import nextcord
from nextcord.ext import commands

from ..bot import BotApp
from ..webutil import WebCog

_logger = getLogger(__name__)


class ErrorHandle(WebCog):
    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        _logger.error("Error in command '%s': %s", ctx.command, error, exc_info=error)
        await ctx.send(
            embed=nextcord.Embed(
                title="Command Error",
                description=(
                    f"An error occurred while executing the command: {self.bot.app.authenticator.mask_password(error)}\n\n"
                    f"```python\n{self.bot.app.authenticator.mask_password("".join(traceback.format_exception(error.original if isinstance(error, (commands.ConversionError, commands.CommandInvokeError)) else error)))}\n```"
                ),
                color=nextcord.Color.red(),
            ).set_footer(text=f"command_error|{self.bot.app.conf['lease_label']}")
        )

    @commands.Cog.listener()
    async def on_application_command_error(
        self, interaction: nextcord.Interaction, error: nextcord.ApplicationError
    ):
        _logger.error(
            "Error in application command '%s': %s",
            interaction.application_command,
            error,
            exc_info=error,
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=nextcord.Embed(
                    title="Application Command Error",
                    description=(
                        f"An error occurred while executing the application command: {self.bot.app.authenticator.mask_password(error)}\n\n"
                        f"```python\n{self.bot.app.authenticator.mask_password("".join(traceback.format_exception(error.original if isinstance(error, nextcord.ApplicationInvokeError) else error)))}\n```"
                    ),
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"application_command_error|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
        else:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Application Command Error",
                    description=(
                        f"An error occurred while executing the application command: {self.bot.app.authenticator.mask_password(error)}\n\n"
                        f"```python\n{self.bot.app.authenticator.mask_password("".join(traceback.format_exception(error.original if isinstance(error, nextcord.ApplicationInvokeError) else error)))}\n```"
                    ),
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"application_command_error|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )


def setup(bot: BotApp):
    bot.add_cog(ErrorHandle(bot))
