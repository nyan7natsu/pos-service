import nextcord
from aiohttp.web import Request, Response
from nextcord.ext import application_checks, commands

from ..bot import BotApp
from ..webutil import WebCog, get


class Refund(WebCog): ...


def setup(bot: BotApp):
    bot.add_cog(Refund(bot))
