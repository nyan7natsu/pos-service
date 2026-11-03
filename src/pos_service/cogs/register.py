from logging import getLogger
from typing import Any, TypedDict, override

import nextcord
from nextcord import SlashOption
from nextcord.ext import application_checks
from nextcord.types import interactions

from ..bot import BotApp
from ..model import (
    CashCount,
    CashCountEvent,
    EventsSource,
    EventsType,
    LedgerEntry,
    LedgerEvent,
    SaleEvent,
)
from ..ui import RadioGroup
from ..webutil import WebCog

_logger = getLogger(__name__)


class Register(WebCog):
    class MismatchModal(nextcord.ui.Modal):
        def __init__(
            self,
            bot: BotApp,
            idempotency_key: str,
            total: int,
            excepted_total: int,
            amount: CashCount,
        ):
            super().__init__(title="Cash Count Mismatch")
            self.bot = bot
            self.idempotency_key = idempotency_key
            self.total = total
            self.excepted_total = excepted_total
            self.amount: CashCount = amount

            self.radio_group = RadioGroup(
                options=[
                    {
                        "label": "Ignore and continue (Adjustment will be made)",
                        "value": "ignore",
                    },
                    {
                        "label": "Cancel operation",
                        "value": "cancel",
                    },
                ],
                custom_id="mismatch_radio",
                required=True,
            )
            self.radio_label = nextcord.components.Label(
                label="Choose an action:",
                description=f"Reported total cash ({self.total} yen) does not match expected total cash ({self.excepted_total} yen).",
                component=self.radio_group,
            )

        @override
        def to_dict(self) -> dict[str, Any]:
            return {
                "title": self.title,
                "custom_id": self.custom_id,
                "components": [
                    self.radio_label.to_dict(),
                ],
            }

        def get_component(
            self, data: interactions.InteractionData, custom_id: str
        ) -> interactions.ComponentInteractionData | None:
            return next(
                (
                    c
                    for c in data.get("components", [])
                    if c.get("component", {}).get("custom_id") == custom_id
                ),
                {},
            ).get("component", None)

        async def callback(self, interaction: nextcord.Interaction):
            assert isinstance(interaction.user, nextcord.User | nextcord.Member)
            assert interaction.data, "Interaction data is None"

            comp = self.get_component(interaction.data, self.radio_group.custom_id)
            if comp is None:
                await interaction.send(
                    "No component data found for the radio group.",
                    ephemeral=True,
                )
                return
            value = comp.get("value")

            if value == "cancel":
                await interaction.send(
                    "Operation cancelled.",
                    ephemeral=True,
                )
                return

            cash_count_event = CashCountEvent(
                idempotency_key=self.idempotency_key,
                type=EventsType.X,
                source=EventsSource.DISCORD,
                cash_delta=self.total - self.excepted_total,
                discount=0,
                operator=interaction.user.id,
                occurred_at=interaction.created_at.isoformat(),
                cash_count=self.amount,
            )
            await self.bot.app.ledger.append(cash_count_event)

            embed = nextcord.Embed(
                title="Cash Count Reported",
                description=f"Reported cash count by {interaction.user.mention}. Total cash: {self.total} yen.\nExpected total cash: {self.excepted_total} yen.\nDifference: {self.total - self.excepted_total} yen.",
                color=nextcord.Color.blue(),
            ).set_footer(
                text=f"x_report|{interaction.id}|{self.bot.app.conf['lease_label']}"
            )

            [
                embed.add_field(
                    name=f"{name.split("_")[1]} yen",
                    value=f"{getattr(self.amount, name)} {'bill(s)' if name in ('yen_1000', 'yen_5000', 'yen_10000') else 'coin(s)'}",
                    inline=True,
                )
                for name in CashCount.model_fields.keys()
            ]

            await interaction.send(
                "Successfully reported cash count.",
                embed=embed,
                ephemeral=True,
            )
            await self.bot.send_log_channel(embed)

    @nextcord.slash_command(name="report", description="Report operations")
    async def slash_report(self, _: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_report.subcommand(name="x", description="Report operation X")
    async def slash_report_x(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int = SlashOption(
            name="yen_10000",
            description="Amount in 10,000 yen units",
            required=True,
        ),
        yen_5000: int = SlashOption(
            name="yen_5000",
            description="Amount in 5,000 yen units",
            required=True,
        ),
        yen_2000: int = SlashOption(
            name="yen_2000",
            description="Amount in 2,000 yen units",
            required=True,
        ),
        yen_1000: int = SlashOption(
            name="yen_1000",
            description="Amount in 1,000 yen units",
            required=True,
        ),
        yen_500: int = SlashOption(
            name="yen_500",
            description="Amount in 500 yen units",
            required=True,
        ),
        yen_100: int = SlashOption(
            name="yen_100",
            description="Amount in 100 yen units",
            required=True,
        ),
        yen_50: int = SlashOption(
            name="yen_50",
            description="Amount in 50 yen units",
            required=True,
        ),
        yen_10: int = SlashOption(
            name="yen_10",
            description="Amount in 10 yen units",
            required=True,
        ),
        yen_5: int = SlashOption(
            name="yen_5",
            description="Amount in 5 yen units",
            required=True,
        ),
        yen_1: int = SlashOption(
            name="yen_1",
            description="Amount in 1 yen units",
            required=True,
        ),
    ):
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

        excepted_total = self.bot.app.ledger.expected_cash()
        total = cash_count.total()

        if total != excepted_total:
            modal = self.MismatchModal(
                bot=self.bot,
                idempotency_key=str(interaction.id),
                total=total,
                excepted_total=excepted_total,
                amount=cash_count,
            )
            await interaction.response.send_modal(modal)
            return

        await interaction.response.defer(ephemeral=True)

        await self.bot.app.ledger.append(
            CashCountEvent(
                idempotency_key=str(interaction.id),
                type=EventsType.X,
                source=EventsSource.DISCORD,
                cash_delta=total - excepted_total,
                discount=0,
                operator=interaction.user.id,
                occurred_at=interaction.created_at.isoformat(),
                cash_count=cash_count,
            )
        )

        embed = nextcord.Embed(
            title="Cash Count Reported",
            description=f"Reported cash count by {interaction.user.mention}. Total cash: {total} yen.\nExpected total cash: {excepted_total} yen.\nDifference: {total - excepted_total} yen.",
            color=nextcord.Color.blue(),
        ).set_footer(
            text=f"x_report|{interaction.id}|{self.bot.app.conf['lease_label']}"
        )

        [
            embed.add_field(
                name=f"{name.split('_')[1]} yen",
                value=f"{getattr(cash_count, name)} {'bill(s)' if name in ('yen_1000', 'yen_5000', 'yen_10000') else 'coin(s)'}",
                inline=True,
            )
            for name in CashCount.model_fields.keys()
        ]

        await interaction.send(
            "Successfully reported cash count.",
            embed=embed,
            ephemeral=True,
        )
        await self.bot.send_log_channel(embed)


def setup(bot: BotApp):
    bot.add_cog(Register(bot))
