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
        self._log_tasks = set()

    async def on_ready(self):
        assert self.user

        await self.change_presence(
            activity=nextcord.Game(name="Online", type=1),
            status=nextcord.Status.online,
        )

        _logger.info(f"Logged in as {self.user} ({self.user.id})")

    def create_log_task(self, message: str, embed: nextcord.Embed):
        task = self.loop.create_task(self.send_log_channel(message, embed))
        self._log_tasks.add(task)
        task.add_done_callback(self._on_log_task_done)

    def _on_log_task_done(self, task: asyncio.Task):
        self._log_tasks.discard(task)
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            _logger.error("Failed to send log message", exc_info=exc)

    async def send_log_channel(self, message: str, embed: nextcord.Embed):
        channel = await self.resolve_channel(self.app.conf["report_channel_id"])
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
