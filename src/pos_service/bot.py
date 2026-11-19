import asyncio
import typing
from logging import getLogger

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

    def create_report_task(self, message: str, embed: nextcord.Embed):
        "レポートチャンネルにメッセージを送信するタスクを作成する"
        self.app.create_task(
            self.send_log_channel(
                message, embed, self.app.conf["report_channel_id"]
            ),
            "bot_report"
        )

    async def send_log_channel(self, message: str, embed: nextcord.Embed, channel_id: int | None = None):
        channel = await self.resolve_channel(channel_id if channel_id else self.app.conf["log_channel_id"])
        assert isinstance(channel, nextcord.TextChannel)
        return await channel.send(message, embed=embed)

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
