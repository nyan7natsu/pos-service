import nextcord
from nextcord.ext import commands

from ..bot import BotApp
from ..model import LedgerEntry, SaleEvent
from ..webutil import WebCog


class PublicLog(WebCog):
    ...


def setup(bot: BotApp):
    bot.add_cog(PublicLog(bot))
