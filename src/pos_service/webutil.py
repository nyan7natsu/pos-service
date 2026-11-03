import typing
from logging import getLogger

from aiohttp.web import Request, Response
from nextcord.ext import commands

if typing.TYPE_CHECKING:
    from .bot import BotApp


class Endpoint(typing.NamedTuple):
    method: str
    url: str


def endpoint(method: str, url: str):
    def decorator(
        func: typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, Response]],
    ):
        func.__setattr__("_endpoint_meta", Endpoint(method=method, url=url))
        return func

    return decorator


def get(url: str):
    "GETリクエストを処理するエンドポイントを定義するデコレーター"

    return endpoint("GET", url)


def post(url: str):
    "POSTリクエストを処理するエンドポイントを定義するデコレーター"

    return endpoint("POST", url)


class WebCog(commands.Cog):
    "Discord BOTのコグで、Webサーバーのエンドポイントを定義するための基底クラス"

    def __init__(self, bot: "BotApp"):
        self.bot = bot
        self.bot.app.web_handler.update(self.endpoints)
        self.logger = getLogger(f"{__name__}.cogs.{self.__class__.__name__}")

    def cog_unload(self):
        for ep in self.endpoints:
            self.bot.app.web_handler.pop(ep, None)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._endpoint_handlers: dict[Endpoint, str] = {}
        for name, value in vars(cls).items():
            meta = getattr(value, "_endpoint_meta", None)
            if meta is not None:
                cls._endpoint_handlers[meta] = name

    @property
    def endpoints(
        self,
    ) -> typing.Mapping[
        Endpoint,
        typing.Callable[[Request], typing.Coroutine[typing.Any, typing.Any, Response]],
    ]:
        return {ep: getattr(self, name) for ep, name in self._endpoint_handlers.items()}
