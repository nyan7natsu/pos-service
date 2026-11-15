import io

import nextcord
from aiohttp.web import HTTPFound, Request, Response
from nextcord.ext import application_checks

from ..bot import BotApp
from ..webutil import WebCog, get, post


class BackStage(WebCog):
    @get("/api/backstage/discord/login")
    async def handler_discord_login(self, request: Request) -> Response:
        return HTTPFound(
            f"https://discord.com/api/oauth2/authorize?client_id={self.bot.app.conf['client_id']}&redirect_uri={request.url.with_path('/api/backstage/discord/redirect')}&response_type=code&scope=identify"
        )

    @get("/api/backstage/discord/redirect")
    async def handler_discord_redirect(self, request: Request) -> Response:
        code = request.query.get("code")
        if not code:
            return Response(text="Missing code", status=400, content_type="text/plain")

        token = (await self.bot.app.discord.get_access_token(
            code, str(request.url.with_path("/api/backstage/discord/redirect"))
        )).access_token

        user_info = await self.bot.app.discord.get_user_info(token)

        return Response(
            text=f"Hello, {user_info.username} (ID: {user_info.id})",
            content_type="text/plain",
        )


def setup(bot: BotApp):
    bot.add_cog(BackStage(bot))
