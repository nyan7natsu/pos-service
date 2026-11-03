import io
from logging import getLogger

import nextcord
from aiohttp.web import Request, Response
from nextcord.ext import application_checks

from ..bot import BotApp
from ..lib.qr import generate_qr_bytes
from ..webutil import WebCog, post


class Auth(WebCog):
    async def get_qr_code(self) -> bytes:
        return await generate_qr_bytes(self.bot.app.authenticator.get_password())

    @nextcord.slash_command(name="password")
    async def slash_password(self, _: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_password.subcommand(name="regen", description="Regenerate the password")
    async def slash_password_regen(self, interaction: nextcord.Interaction):
        self.bot.app.authenticator.regen_password()
        qr = await self.get_qr_code()
        await interaction.send(
            "Password regenerated.",
            ephemeral=True,
            file=nextcord.File(io.BytesIO(qr), filename="password.png"),
        )

    @application_checks.guild_only()
    @slash_password.subcommand(name="show", description="Show the current password")
    async def slash_password_show(self, interaction: nextcord.Interaction):
        qr = await self.get_qr_code()
        await interaction.send(
            "Current password:",
            ephemeral=True,
            file=nextcord.File(io.BytesIO(qr), filename="password.png"),
        )

    @post("/api/auth")
    async def handler_check_password(self, request: Request) -> Response:
        data: dict = await request.json()
        password = data.get("password", "")
        if self.bot.app.authenticator.check_password(password):
            return Response(text="OK", content_type="text/plain")
        else:
            return Response(text="Unauthorized", status=401, content_type="text/plain")


def setup(bot: BotApp):
    bot.add_cog(Auth(bot))
