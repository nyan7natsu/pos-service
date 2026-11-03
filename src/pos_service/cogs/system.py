import nextcord
from aiohttp.web import Request, Response
from nextcord.ext import application_checks, commands

from ..bot import BotApp
from ..webutil import WebCog, get


class System(WebCog):
    @commands.command(name="health")
    async def ctx_health(self, ctx: commands.Context):
        await ctx.send(
            embed=nextcord.Embed(
                title="Health Check",
                description=f"OK!\n{self.bot.latency*1000:.2f}ms",
                color=nextcord.Color.green(),
            ).set_footer(text=f"health_check|{self.bot.app.conf['lease_label']}")
        )

    @application_checks.guild_only()
    @nextcord.slash_command(name="shutdown", description="Shutdown the bot")
    async def slash_shutdown(self, interaction: nextcord.Interaction):
        await interaction.send(
            embed=nextcord.Embed(
                title="Shutdown",
                description="Shutting down the bot (call `POSService.shutdown`)...",
                color=nextcord.Color.yellow(),
            ).set_footer(text=f"shutdown_log|{self.bot.app.conf['lease_label']}"),
            ephemeral=False,
        )
        self.bot.app.request_stop()

    @application_checks.guild_only()
    @nextcord.slash_command(name="health", description="Check the health of the bot")
    async def slash_health(self, interaction: nextcord.Interaction):
        await interaction.send(
            embed=nextcord.Embed(
                title="Health Check",
                description=f"OK!\n{self.bot.latency*1000:.2f}ms",
                color=nextcord.Color.green(),
            ).set_footer(text=f"health_check|{self.bot.app.conf['lease_label']}"),
            ephemeral=True,
        )

    @get("/api/health")
    async def handle_health(self, _: Request) -> Response:
        return Response(text="OK", content_type="text/plain")


def setup(bot: BotApp):
    bot.add_cog(System(bot))
