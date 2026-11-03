import nextcord
from nextcord import SlashOption
from nextcord.ext import application_checks

from ..bot import BotApp
from ..model import CashCount, CashInEvent, CashOutEvent, EventsSource, EventsType
from ..webutil import WebCog


class Cash(WebCog):
    @nextcord.slash_command(name="cash", description="Cash operations")
    async def slash_cash(self, _: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_cash.subcommand(name="in", description="Cash in operation")
    async def slash_cash_in(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int | None = SlashOption(
            name="yen_10000",
            description="Number of 10,000 yen bills",
            required=False,
        ),
        yen_5000: int | None = SlashOption(
            name="yen_5000",
            description="Number of 5,000 yen bills",
            required=False,
        ),
        yen_2000: int | None = SlashOption(
            name="yen_2000",
            description="Number of 2,000 yen bills",
            required=False,
        ),
        yen_1000: int | None = SlashOption(
            name="yen_1000",
            description="Number of 1,000 yen bills",
            required=False,
        ),
        yen_500: int | None = SlashOption(
            name="yen_500",
            description="Number of 500 yen coins",
            required=False,
        ),
        yen_100: int | None = SlashOption(
            name="yen_100",
            description="Number of 100 yen coins",
            required=False,
        ),
        yen_50: int | None = SlashOption(
            name="yen_50",
            description="Number of 50 yen coins",
            required=False,
        ),
        yen_10: int | None = SlashOption(
            name="yen_10",
            description="Number of 10 yen coins",
            required=False,
        ),
        yen_5: int | None = SlashOption(
            name="yen_5",
            description="Number of 5 yen coins",
            required=False,
        ),
        yen_1: int | None = SlashOption(
            name="yen_1",
            description="Number of 1 yen coins",
            required=False,
        ),
    ):
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
        assert cash_count.is_only_positive(), "Amount must be positive"

        event = CashInEvent(
            idempotency_key=str(interaction.id),
            type=EventsType.CASH_IN,
            source=EventsSource.DISCORD,
            cash_delta=amount,
            discount=0,
            operator=interaction.user.id,
            occurred_at=interaction.created_at.isoformat(),
            cash_count=cash_count,
        )

        await self.bot.app.ledger.append(event)

        all_amount = self.bot.app.ledger.expected_cash()

        embed = nextcord.Embed(
            title="Cash In",
            description=f"Cashed in: {amount} yen\nTotal cash: {all_amount} yen",
            color=nextcord.Color.green(),
        ).set_footer(
            text=f"cash_in|{interaction.id}|{self.bot.app.conf['lease_label']}"
        )

        await interaction.send(
            "Successfully cashed in.",
            embed=embed,
            ephemeral=True,
        )
        await self.bot.send_log_channel(embed)

    @application_checks.guild_only()
    @slash_cash.subcommand(name="out", description="Cash out operation")
    async def slash_cash_out(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int | None = SlashOption(
            name="yen_10000",
            description="Number of 10,000 yen bills",
            required=False,
        ),
        yen_5000: int | None = SlashOption(
            name="yen_5000",
            description="Number of 5,000 yen bills",
            required=False,
        ),
        yen_2000: int | None = SlashOption(
            name="yen_2000",
            description="Number of 2,000 yen bills",
            required=False,
        ),
        yen_1000: int | None = SlashOption(
            name="yen_1000",
            description="Number of 1,000 yen bills",
            required=False,
        ),
        yen_500: int | None = SlashOption(
            name="yen_500",
            description="Number of 500 yen coins",
            required=False,
        ),
        yen_100: int | None = SlashOption(
            name="yen_100",
            description="Number of 100 yen coins",
            required=False,
        ),
        yen_50: int | None = SlashOption(
            name="yen_50",
            description="Number of 50 yen coins",
            required=False,
        ),
        yen_10: int | None = SlashOption(
            name="yen_10",
            description="Number of 10 yen coins",
            required=False,
        ),
        yen_5: int | None = SlashOption(
            name="yen_5",
            description="Number of 5 yen coins",
            required=False,
        ),
        yen_1: int | None = SlashOption(
            name="yen_1",
            description="Number of 1 yen coins",
            required=False,
        ),
    ):
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
        assert cash_count.is_only_positive(), "Amount must be positive"

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
                    title="Cash Out Failed",
                    description=f"Invalid cash count: {', '.join(insuficient_fields)}. All counts must be non-negative.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"cash_out_failed|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        if amount > all_amount:
            await interaction.send(
                embed=nextcord.Embed(
                    title="Cash Out Failed",
                    description=f"Insufficient funds. Attempted to cash out {amount} yen, but only {all_amount} yen is available.",
                    color=nextcord.Color.red(),
                ).set_footer(
                    text=f"cash_out_failed|{self.bot.app.conf['lease_label']}"
                ),
                ephemeral=True,
            )
            return

        event = CashOutEvent(
            idempotency_key=str(interaction.id),
            type=EventsType.CASH_OUT,
            source=EventsSource.DISCORD,
            cash_delta=-amount,
            discount=0,
            operator=interaction.user.id,
            occurred_at=interaction.created_at.isoformat(),
            cash_count=cash_count,
        )
        await self.bot.app.ledger.append(event)

        new_total = all_amount - amount

        embed = nextcord.Embed(
            title="Cash Out",
            description=f"Cashed out: {amount} yen\nTotal cash: {new_total} yen",
            color=nextcord.Color.orange(),
        ).set_footer(
            text=f"cash_out|{interaction.id}|{self.bot.app.conf['lease_label']}"
        )

        await interaction.send(
            "Successfully cashed out.",
            embed=embed,
            ephemeral=True,
        )
        await self.bot.send_log_channel(embed)

    @application_checks.guild_only()
    @slash_cash.subcommand(name="total", description="Check the total cash amount")
    async def slash_cash_total(self, interaction: nextcord.Interaction):
        all_amount = self.bot.app.ledger.expected_cash()
        expected_cash_count = self.bot.app.ledger.get_cash_count()

        embed = (
            nextcord.Embed(
                title="Total Cash",
                description=f"Current total cash: {all_amount} yen",
                color=nextcord.Color.blue(),
            )
            .set_footer(text=f"cash_total|{self.bot.app.conf['lease_label']}")
            .add_field(
                name="Cash Count",
                value="\n".join(
                    f"{field}: {getattr(expected_cash_count, field)}"
                    for field in CashCount.model_fields.keys()
                ),
                inline=False,
            )
        )

        await interaction.send(
            embed=embed,
            ephemeral=True,
        )


def setup(bot: BotApp):
    bot.add_cog(Cash(bot))
