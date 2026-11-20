import datetime
import secrets

import nextcord
from aiohttp.web import HTTPFound, Request, Response
from nextcord.ext import application_checks

from ..bot import BotApp
from ..webutil import WebCog, get


class BackStage(WebCog):
    EXPIRES: datetime.timedelta = datetime.timedelta(minutes=30)

    def __init__(self, bot: BotApp):
        super().__init__(bot)
        self.__sessions: dict[str, tuple[int, datetime.datetime]] = {}

    def get_session_user_id(self, request: Request) -> int | None:
        session = request.cookies.get("backstage_session")
        if not session:
            return None
        if not self.is_session_key_valid(session):
            return None
        user_id, _ = self.__sessions[session]
        return user_id

    def is_session_valid(self, request: Request) -> bool:
        session = request.cookies.get("backstage_session")
        if not session:
            return False
        return self.is_session_key_valid(session)

    def is_session_key_valid(self, session: str) -> bool:
        if session not in self.__sessions:
            return False
        user_id, expires_at = self.__sessions[session]
        if datetime.datetime.now() > expires_at:
            del self.__sessions[session]
            return False

        guild = self.bot.get_guild(self.bot.app.conf["guild_ids"][0])
        if guild is None:
            return False
        member = guild.get_member(user_id)
        if member is None:
            return False

        if any(role.id == self.bot.app.conf["admin_role_id"] for role in member.roles):
            return True

        return False

    @get("/api/backstage/discord/login")
    async def handler_discord_login(self, _: Request) -> Response:
        if self.bot.user is None:
            raise RuntimeError("Bot user is not ready")
        return HTTPFound(
            f"https://discord.com/api/oauth2/authorize?client_id={self.bot.user.id}&redirect_uri={self.bot.app.conf["public_host"]}/api/backstage/discord/redirect&response_type=code&scope=identify"
        )

    @get("/api/backstage/discord/redirect")
    async def handler_discord_redirect(self, request: Request) -> Response:
        code = request.query.get("code")
        if not code:
            return Response(text="Missing code", status=400, content_type="text/plain")

        token = (await self.bot.app.discord.get_access_token(
            code,
            self.bot.app.conf["public_host"] +
            "/api/backstage/discord/redirect"
        )).access_token

        try:
            user_info = await self.bot.app.discord.get_user_info(token)
            session = secrets.token_urlsafe(32)
            self.__sessions[session] = (
                int(user_info.id),
                datetime.datetime.now() + self.EXPIRES,
            )

            resp = HTTPFound("/backstage")
            resp.set_cookie(
                "backstage_session", session,
                max_age=int(self.EXPIRES.total_seconds())
            )
            return resp
        except Exception as e:
            return Response(text=f"Failed to get user info: {e}", status=500, content_type="text/plain")

    @get("/api/backstage/discord/logout")
    async def handler_discord_logout(self, request: Request) -> Response:
        session = request.cookies.get("backstage_session")
        if session and session in self.__sessions:
            del self.__sessions[session]

        resp = Response(
            text="Logged out.<br><a href='/api/backstage/discord/login'>Re login</a>",
            content_type="text/html"
        )
        resp.del_cookie("backstage_session")
        return resp

    @nextcord.slash_command(name="backstage", description="Access the backstage")
    async def slash_backstage(self, interaction: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_backstage.subcommand(name="revoke", description="Revoke all backstage sessions")
    async def slash_backstage_revoke(self, interaction: nextcord.Interaction):
        assert isinstance(interaction.user, nextcord.Member)

        if not any(role.id == self.bot.app.conf["admin_role_id"] for role in interaction.user.roles):
            await interaction.send(
                "You do not have permission to revoke backstage sessions.",
                ephemeral=True,
            )
            return

        self.__sessions.clear()
        await interaction.send(
            "All backstage sessions have been revoked.",
            ephemeral=True,
        )

def setup(bot: BotApp):
    bot.add_cog(BackStage(bot))
