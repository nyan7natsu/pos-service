import nextcord
from nextcord import SlashOption
from nextcord.ext import application_checks

from ..bot import BotApp
from ..lib.product import Product
from ..model import (CashCount, CashInEvent, CashOutEvent, EventsSource,
                     EventsType, RefundEvent, RefundItem)
from ..webutil import WebCog


class Refund(WebCog):
    @nextcord.slash_command(name="refund")
    @application_checks.guild_only()
    async def slash_refund(
        self,
        interaction: nextcord.Interaction,
        product_id: str = SlashOption(
            name="product",
            description="Product ID to refund",
            required=True,
        ),
        quantity: int = SlashOption(
            name="quantity",
            description="Quantity to refund",
            required=True,
        ),
        reason: str = SlashOption(
            name="reason",
            description="Reason for the refund",
            required=True,
        ), yen_10000: int = SlashOption(
            name="yen_10000",
            description="Number of 10,000 yen bills",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_5000: int = SlashOption(
            name="yen_5000",
            description="Number of 5,000 yen bills",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_2000: int = SlashOption(
            name="yen_2000",
            description="Number of 2,000 yen bills",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_1000: int = SlashOption(
            name="yen_1000",
            description="Number of 1,000 yen bills",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_500: int = SlashOption(
            name="yen_500",
            description="Number of 500 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_100: int = SlashOption(
            name="yen_100",
            description="Number of 100 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_50: int = SlashOption(
            name="yen_50",
            description="Number of 50 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_10: int = SlashOption(
            name="yen_10",
            description="Number of 10 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_5: int = SlashOption(
            name="yen_5",
            description="Number of 5 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
        yen_1: int = SlashOption(
            name="yen_1",
            description="Number of 1 yen coins",
            required=False,
            min_value=0,
            default=0,
        ),
    ):
        if not self.bot.app.ledger.is_open():
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description="Cannot process refund because the ledger is not open.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        assert isinstance(interaction.user, nextcord.User | nextcord.Member)

        cash_count = CashCount(
            yen_10000=yen_10000,
            yen_5000=yen_5000,
            yen_2000=yen_2000,
            yen_1000=yen_1000,
            yen_500=yen_500,
            yen_100=yen_100,
            yen_50=yen_50,
            yen_10=yen_10,
            yen_5=yen_5,
            yen_1=yen_1,
        )

        amount = cash_count.total()
        if cash_count.is_only_negative() or amount <= 0:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description="Refund amount must be positive and cash count must not be negative.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        try:
            product_id_int = int(product_id)
        except ValueError:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description=f"Invalid product ID: {product_id}. Must be an integer or valid product ID.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        if (product := self.bot.app.product_manager.get_product(product_id_int)) is None:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description=f"Product with ID `{product_id}` not found.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        if quantity <= 0:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description="Quantity must be greater than zero.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        if product.price * quantity != amount:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description=f"Refund amount does not match product price. Expected ¥{product.price * quantity}, got ¥{amount}.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        all_amount = self.bot.app.ledger.expected_cash()
        expected_cash_count = self.bot.app.ledger.get_cash_count()

        insuficient_fields = [
            field
            for field in CashCount.model_fields.keys()
            if getattr(cash_count, field) is not None
            and getattr(expected_cash_count, field) is not None
            and getattr(cash_count, field) > getattr(expected_cash_count, field)
        ]

        if insuficient_fields:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description=f"Invalid cash count: {', '.join(insuficient_fields)}.\nAll counts must not exceed the available cash count.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        if amount > all_amount:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Refund Failed",
                    description=f"Refund amount exceeds available cash.\nAvailable: ¥{all_amount}, Refund: ¥{amount}.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"refund_failed|{interaction.id}|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        event = RefundEvent(
            idempotency_key=str(interaction.id),
            type=EventsType.REFUND,
            source=EventsSource.DISCORD,
            cash_delta=-amount,
            discount=0,
            operator=interaction.user.id,
            reason=reason,
            cash_count=-cash_count,
            occurred_at=interaction.created_at,
            items=(RefundItem(
                product_id=product_id_int,
                quantity=-quantity,
                unit_price=product.price,
            ),)
        )

        await (await self.bot.app.ledger.append(event))[1]

        embed = nextcord.Embed(
            title="Refund Processed",
            description=f"Refund of ¥{amount} for product `{product.name}` (ID: {product_id}) processed successfully.",
            color=nextcord.Color.green(),
        ).set_footer(
            text=f"refund_processed|{interaction.id}|{self.bot.app.conf['lease_label']}"
        )
        await interaction.send(embed=embed, ephemeral=True)

        await self.bot.send_log_channel(embed=embed)

    @slash_refund.on_autocomplete("product_id")
    async def refund_product_autocomplete(
        self, interaction: nextcord.Interaction, product_id: str
    ):
        choices = {
            f"{p.name}（¥{p.price}）(#{p.id})": str(p.id)
            for p in self.bot.app.product_manager.products
            if product_id.lower() in p.name.lower()
        }
        await interaction.response.send_autocomplete(dict(list(choices.items())[:25]))




def setup(bot: BotApp):
    bot.add_cog(Refund(bot))
