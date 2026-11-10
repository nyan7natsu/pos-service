from logging import getLogger

import nextcord
from nextcord.ext import application_checks, tasks

from ..bot import BotApp
from ..webutil import WebCog

_logger = getLogger(__name__)


class Lease(WebCog):
    def __init__(self, bot: BotApp):
        super().__init__(bot)
        self.renew_lease.start()

    def cog_unload(self):
        self.renew_lease.cancel()

    @tasks.loop(seconds=10)
    async def renew_lease(self):
        "定期的にリースを更新します。"
        await self.bot.wait_until_ready()

        async with self.bot.app.session.post(
            f"{self.bot.app.lease_api_url}/lease/acquire",
            json={
                "service_id": self.bot.app.SERVICE_ID,
                "lease_id": self.bot.app.id,
                "lease_label": self.bot.app.conf["lease_label"],
            },
        ) as resp:
            if resp.status == 423:
                _logger.warning("Lease expired! Exiting...")
                await self.bot.send_log_channel(
                    embed=nextcord.Embed(
                        title="Lease Expired!",
                        description="The lease has expired. The bot will shut down.",
                        color=nextcord.Color.red(),
                    ).set_footer(
                        text=f"expired_log|{0}|{self.bot.app.conf['lease_label']}"
                    ),
                )
                self.bot.app.request_stop(False)
            elif resp.status != 200:
                _logger.error("Lease renewal failed with status: %s", resp.status)
            else:
                _logger.debug("Lease renewed successfully.")

    @nextcord.slash_command(name="lease")
    async def slash_lease(self, _: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_lease.subcommand(name="status", description="Check the current lease status")
    async def slash_lease_status(self, interaction: nextcord.Interaction):
        async with self.bot.app.session.get(
            f"{self.bot.app.lease_api_url}/lease/status?service_id={self.bot.app.SERVICE_ID}"
        ) as resp:
            if resp.status != 200:
                await interaction.send(
                    f"Failed to get lease status. Status code: {resp.status}",
                    ephemeral=True,
                )
                return

            await interaction.send(
                embed=nextcord.Embed(
                    title="Lease Status",
                    description=await resp.text(),
                    color=nextcord.Color.green(),
                ).set_footer(text=f"lease_status|0|{self.bot.app.conf['lease_label']}"),
            )

    @application_checks.guild_only()
    @slash_lease.subcommand(name="renew", description="Manually renew the lease")
    async def slash_lease_renew(self, interaction: nextcord.Interaction):
        async with self.bot.app.session.post(
            f"{self.bot.app.lease_api_url}/lease/acquire",
            json={
                "service_id": self.bot.app.SERVICE_ID,
                "lease_id": self.bot.app.id,
                "lease_label": self.bot.app.conf["lease_label"],
            },
        ) as resp:
            if resp.status == 423:
                await interaction.send(
                    embed=nextcord.Embed(
                        title="Lease Expired!",
                        description="The lease has expired. The bot will shut down.",
                        color=nextcord.Color.red(),
                    ).set_footer(
                        text=f"expired_log|0|{self.bot.app.conf['lease_label']}"
                    ),
                    ephemeral=True,
                )
                self.bot.app.request_stop(False)
            elif resp.status != 200:
                await interaction.send(
                    embed=nextcord.Embed(
                        title="Lease Renewal Failed",
                        description=f"Failed to renew lease. Status code: {resp.status}",
                        color=nextcord.Color.red(),
                    ).set_footer(
                        text=f"renew_failed_log|0|{self.bot.app.conf['lease_label']}"
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.send(
                    embed=nextcord.Embed(
                        title="Lease Renewed",
                        description="Lease renewed successfully.",
                        color=nextcord.Color.green(),
                    ).set_footer(
                        text=f"renewed_log|0|{self.bot.app.conf['lease_label']}"
                    ),
                    ephemeral=True,
                )


def setup(bot: BotApp):
    bot.add_cog(Lease(bot))
