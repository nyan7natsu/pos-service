import typing

import nextcord
from aiohttp.web import Request, Response
from nextcord.ext import application_checks, commands

from ..bot import BotApp
from ..model import LedgerEntry, LedgerEvent, SaleEvent
from ..webutil import WebCog, get

if typing.TYPE_CHECKING:
    from .sales import SaleData


class PublicLog(WebCog):
    @commands.Cog.listener()
    async def on_sale_processed(self, entry: LedgerEntry[SaleEvent]):
        embed = (
            nextcord.Embed(
                title=f"#{entry.id}",
                description=f"Sale processed successfully.\n"
                + "\n".join(
                    [
                        f"**{item.product_id}** @ ¥{item.unit_price}x{item.quantity} (¥{item.unit_price * item.quantity})"
                        for item in entry.event.items
                    ]
                ),
                color=nextcord.Color.green(),
            )
            .add_field(name="Discount", value=f"¥{entry.event.discount}", inline=False)
            .set_footer(
                text=f"sale_processed|{entry.event.idempotency_key}|{self.bot.app.conf['lease_label']}"
            )
        )

        await self.bot.send_log_channel(embed=embed)


def setup(bot: BotApp):
    bot.add_cog(PublicLog(bot))
