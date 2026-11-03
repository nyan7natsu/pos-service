import typing
from logging import getLogger

import aiohttp
import nextcord
from nextcord.ext import commands

if typing.TYPE_CHECKING:
    from .pos import POSService

_logger = getLogger(__name__)


class BotApp(commands.Bot):
    "Discord BOTのアプリケーションクラス"

    def __init__(self, app: "POSService", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    async def on_ready(self):
        assert self.user

        await self.change_presence(
            activity=nextcord.Game(name="Online", type=1),
            status=nextcord.Status.online,
        )

        _logger.info(f"Logged in as {self.user} ({self.user.id})")

    async def send_log_channel(self, embed: nextcord.Embed):
        channel = await self.resolve_channel(self.app.conf["report_channel_id"])
        assert isinstance(channel, nextcord.TextChannel)
        await channel.send(embed=embed)

    async def resolve_channel(
        self, channel_id: int
    ) -> (
        nextcord.abc.GuildChannel
        | nextcord.Thread
        | nextcord.abc.PrivateChannel
        | nextcord.PartialMessageable
    ):
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)
        return channel
