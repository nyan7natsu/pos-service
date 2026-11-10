import asyncio
import os
import signal
import sys
import typing
from logging import getLogger

import aiohttp
import nextcord
from aiohttp.web import Application, AppRunner, HTTPFound, Request, Response, TCPSite

from .auth import Authenticator
from .bot import BotApp
from .lib.ledger import LedgerManager
from .lib.product import ProductManager
from .webutil import Endpoint

_logger = getLogger(__name__)

VITE_DEV_SERVER: typing.Final[str] = "http://localhost:5173"


class GeneralConfig(typing.TypedDict):
    discord_token: str
    host: str
    port: int
    guild_ids: list[int]
    cogs: list[str]
    lease_api_url: str
    lease_label: str
    report_channel_id: int


class POSService:
    SERVICE_ID: typing.Final[str] = "pos"
    _session: aiohttp.ClientSession | None = None
    __shutdown_event: asyncio.Event
    __release_lease_on_shutdown: bool = True
    runner: AppRunner
    bot_task: asyncio.Task | None = None
    ledger_task: asyncio.Task | None = None
    authenticator: Authenticator

    def __init__(self, id: str, conf: GeneralConfig):
        self.id = id
        self.conf = conf
        self.lease_api_url = (
            conf["lease_api_url"].endswith("/")
            and conf["lease_api_url"][:-1]
            or conf["lease_api_url"]
        )

        self.loop = asyncio.new_event_loop()

        self.__shutdown_event = asyncio.Event()

        self.authenticator = Authenticator()
        self.ledger = LedgerManager(pos=self, filename="ledger.jsonl")
        self.product_manager = ProductManager(pos=self, filename="products.yaml")

        self.web = Application(loop=self.loop)
        self.bot = BotApp(
            self,
            loop=self.loop,
            command_prefix="p!",
            intents=nextcord.Intents.all(),
            default_guild_ids=self.conf["guild_ids"],
            help_command=None,
            status=nextcord.Status.dnd,
            activity=nextcord.Game(name="Loading...", type=1),
        )

        self.web.on_startup.append(self.web_on_startup)
        self.web["app"] = self

        self.web_handler: dict[
            Endpoint, typing.Callable[[Request], typing.Awaitable[Response]]
        ] = {}

        self.web.router.add_get("/", self.index_redirect)
        self.web.router.add_route("*", "/api/{tail:.+}", self.handle_request)

        if "-d" in sys.argv or "--dev" in sys.argv:
            _logger.info("Running in development mode. Proxying to Vite dev server.")
            self.web.router.add_route("*", "/{tail:.*}", self.proxy_to_vite)
        else:
            self.web.router.add_static("/", "frontend/dist", show_index=False)

        for cog in self.conf.get("cogs", []):
            _logger.info("Loading Extension: %s", cog)
            self.bot.load_extension(cog)

        self.runner = AppRunner(self.web)

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(loop=self.loop)
        return self._session

    async def handle_request(self, request: Request) -> Response:
        endpoint = Endpoint(method=request.method, url=request.path)
        handler = self.web_handler.get(endpoint)
        if handler is None:
            return Response(status=404, text="Not Found")
        return await handler(request)

    async def index_redirect(self, _) -> Response:
        "これを入れないと Forbidden になるか，ディレクトリの一覧が表示されてしまう..."
        raise HTTPFound("/index.html")

    async def proxy_to_vite(self, request: Request) -> Response:
        "開発モード中は，フロントエンドへのリクエストはviteに流す"
        async with aiohttp.ClientSession() as session:
            url = f"{VITE_DEV_SERVER}{request.path_qs}"
            async with session.request(
                request.method,
                url,
                headers={
                    k: v for k, v in request.headers.items() if k.lower() != "host"
                },
                data=await request.read(),
            ) as resp:
                return Response(
                    status=resp.status,
                    body=await resp.read(),
                    headers={
                        k: v
                        for k, v in resp.headers.items()
                        if k.lower()
                        not in (
                            "content-encoding",
                            "transfer-encoding",
                            "content-length",
                        )
                    },
                )

    async def bot_start(self):
        _logger.info("Starting the bot...")
        await self.bot.start(self.conf["discord_token"])

    async def get_lease_status(self) -> int:
        try:
            async with self.session.post(
                f"{self.lease_api_url}/lease/acquire",
                json={
                    "service_id": self.SERVICE_ID,
                    "lease_id": self.id,
                    "lease_label": self.conf["lease_label"],
                },
            ) as resp:
                return resp.status
        except Exception as e:
            _logger.error("Lease check failed: %s", e)
            return 500

    async def check_lease(self) -> bool:
        while True:
            status = await self.get_lease_status()
            if status == 200:
                return True
            elif status == 423:
                _logger.error("Lease is locked by another instance. Shutting down...")
                self.request_stop(False)
                sys.exit(1)
            else:
                _logger.warning(
                    "Lease check failed with status: %s. Retrying in 10 seconds...",
                    status,
                )
                try:
                    await asyncio.wait_for(self.__shutdown_event.wait(), timeout=10)
                    return False
                except TimeoutError:
                    pass

    async def web_start(self):
        _logger.info("Starting the web server...")
        await self.runner.setup()
        await TCPSite(self.runner, self.conf["host"], self.conf["port"]).start()

        if self.bot_task is None:
            raise RuntimeError("Bot task is not initialized. Something went wrong.")

        stop_task = asyncio.create_task(self.__shutdown_event.wait(), name="stop")
        done, _ = await asyncio.wait(
            {self.bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        stop_task.cancel()

        if self.bot_task in done:
            if not self.bot_task.cancelled() and (exc := self.bot_task.exception()):
                _logger.error("The bot stopped unexpectedly.", exc_info=exc)
            else:
                _logger.warning("The bot stopped.")

        await self.shutdown()

    def start(self):
        _logger.info("Checking lease with ID: %s", self.id)
        lease_result = self.loop.run_until_complete(self.check_lease())
        if lease_result:
            _logger.info("Lease acquired successfully.")
            self.loop.run_until_complete(self.web_start())
        else:
            _logger.error("Failed to acquire lease. Exiting...")
            sys.exit(0)

    async def web_on_startup(self, _):
        await self.authenticator.load_password_file()
        await self.product_manager.load()
        await self.ledger.load()
        self.ledger_task = self.loop.create_task(self.ledger.run(), name="ledger")
        self.bot_task = self.loop.create_task(self.bot_start(), name="bot")
        try:
            await asyncio.wait_for(self.bot.wait_until_ready(), timeout=30)
        except asyncio.TimeoutError:
            _logger.error("Bot failed to start within 30 seconds. Shutting down...")
            await self.shutdown()
            sys.exit(1)
        _logger.info("Bot is ready!")

    def _install_signal_handlers(self) -> None:
        def on_signal(sig: signal.Signals) -> None:
            _logger.info(f"Received signal {sig.name}. Shutting down...")
            self.__shutdown_event.set()
            self.loop.remove_signal_handler(sig)

        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, on_signal, sig)

    def request_stop(self, release_lease: bool = True):
        _logger.info("Shutdown requested. Releasing lease: %s", release_lease)
        if not release_lease:
            self.__release_lease_on_shutdown = False
        self.__shutdown_event.set()

    async def shutdown(self):
        try:
            [self.bot.unload_extension(ext) for ext in list(self.bot.extensions.keys())]
        except Exception as e:
            _logger.error("Error while unloading extensions: %s", e)

        # BOTの停止
        try:
            await asyncio.wait_for(self.bot.close(), timeout=10)
            if self.bot_task:
                self.bot_task.cancel()
        except Exception as e:
            _logger.error("Error while cancelling bot task: %s", e)

        # Webサーバの停止
        try:
            await self.runner.cleanup()
        except Exception as e:
            _logger.error("Error while shutting down web server: %s", e)

        # 台帳書き込みの停止
        try:
            await asyncio.wait_for(self.ledger.queue.join(), timeout=10)
            if self.ledger_task:
                self.ledger_task.cancel()
        except Exception as e:
            _logger.error("Error while cancelling ledger task: %s", e)

        if self.__release_lease_on_shutdown:
            try:
                _logger.info("Releasing lease with ID: %s", self.id)
                async with self.session.post(
                    f"{self.lease_api_url}/lease/release",
                    json={
                        "service_id": self.SERVICE_ID,
                        "lease_id": self.id,
                        "lease_label": self.conf["lease_label"],
                    },
                ) as resp:
                    if resp.status != 200:
                        _logger.error(
                            "Lease release failed with status %s", resp.status
                        )
                    else:
                        _logger.info("Lease released successfully")
            except Exception as e:
                _logger.error("Lease release failed: %s", e)

        await self.session.close()

    def run(self):
        _logger.info("Starting the application...")
        self._install_signal_handlers()
        self.start()
