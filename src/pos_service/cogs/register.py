import asyncio
from logging import getLogger
from typing import Any, Literal, TypedDict, override

import nextcord
from aiohttp.web import Request, Response, json_response
from nextcord import SlashOption
from nextcord.ext import application_checks
from nextcord.types import interactions

from ..bot import BotApp
from ..model import (CashCount, CashCountEvent, CloseEvent, EventsSource,
                     EventsType, LedgerEntry, LedgerEvent, OpenEvent,
                     SaleEvent)
from ..ui import RadioGroup
from ..webutil import WebCog, get, post


class Register(WebCog):
    class MismatchModal(nextcord.ui.Modal):
        result: asyncio.Future[tuple[Literal["adjust",
                                             "ignore", "cancel"], nextcord.Interaction]]

        def __init__(
            self,
            bot: BotApp,
            idempotency_key: str,
            total: int,
            excepted_total: int,
            amount: CashCount,
            enable_adjust_button: bool = True,
            enable_ignore_button: bool = True,
        ):
            super().__init__(title="Cash Count Mismatch")
            self.bot = bot
            self.idempotency_key = idempotency_key
            self.total = total
            self.excepted_total = excepted_total
            self.amount: CashCount = amount
            self.result = asyncio.get_running_loop().create_future()

            options = []
            if enable_adjust_button:
                options.append(
                    {
                        "label": "Adjust register to match reported cash count",
                        "value": "adjust",
                    }
                )
            if enable_ignore_button:
                options.append(
                    {
                        "label": "Ignore mismatch and proceed with operation",
                        "value": "ignore",
                    }
                )
            options.append(
                {
                    "label": "Cancel operation",
                    "value": "cancel",
                }
            )

            self.radio_group = RadioGroup(
                options=options,
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
            assert isinstance(interaction.user,
                              nextcord.User | nextcord.Member)
            assert interaction.data, "Interaction data is None"

            await interaction.response.defer(ephemeral=True, with_message=True)

            if self.result.done():
                await interaction.send(
                    "This modal has already been processed. Please wait for the operation to complete.",
                    ephemeral=True,
                )
                return

            comp = self.get_component(
                interaction.data, self.radio_group.custom_id)
            if comp is None:
                self.result.set_result(("cancel", interaction))
                return

            value: Literal["adjust", "ignore", "cancel"] = comp.get(
                "value")  # type: ignore

            self.result.set_result((value, interaction))

    @nextcord.slash_command(name="register", description="Register operations")
    async def slash_register(self, _: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_register.subcommand(name="open", description="Open the register")
    async def slash_open_register(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int = SlashOption(
            name="yen_10000",
            description="Amount in 10,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_5000: int = SlashOption(
            name="yen_5000",
            description="Amount in 5,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_2000: int = SlashOption(
            name="yen_2000",
            description="Amount in 2,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_1000: int = SlashOption(
            name="yen_1000",
            description="Amount in 1,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_500: int = SlashOption(
            name="yen_500",
            description="Amount in 500 yen units",
            min_value=0,
            required=True,
        ),
        yen_100: int = SlashOption(
            name="yen_100",
            description="Amount in 100 yen units",
            min_value=0,
            required=True,
        ),
        yen_50: int = SlashOption(
            name="yen_50",
            description="Amount in 50 yen units",
            min_value=0,
            required=True,
        ),
        yen_10: int = SlashOption(
            name="yen_10",
            description="Amount in 10 yen units",
            min_value=0,
            required=True,
        ),
        yen_5: int = SlashOption(
            name="yen_5",
            description="Amount in 5 yen units",
            min_value=0,
            required=True,
        ),
        yen_1: int = SlashOption(
            name="yen_1",
            description="Amount in 1 yen units",
            min_value=0,
            required=True,
        ),
    ):
        if self.bot.app.ledger.is_open():
            await interaction.send(
                "Cannot open the register because it is already open :D",
                ephemeral=True,
            )
            return

        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        assert isinstance(interaction.channel, nextcord.TextChannel)

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
        modal_sent = False
        sendable_interaction: nextcord.Interaction = interaction

        last_event_id = self.bot.app.ledger.last_id()

        if last_event_id != 0 and total != excepted_total:
            modal = self.MismatchModal(
                bot=self.bot,
                idempotency_key=str(interaction.id),
                total=total,
                excepted_total=excepted_total,
                amount=cash_count,
                enable_ignore_button=False,
            )
            await interaction.response.send_modal(modal)
            try:
                result = await asyncio.wait_for(modal.result, timeout=120)
            except asyncio.TimeoutError:
                modal.stop()
                raise asyncio.TimeoutError("Modal interaction timed out.")

            if result[0] == "cancel":
                await result[1].send(
                    "Operation canceled due to cash count mismatch.",
                    ephemeral=True,
                )
                return
            sendable_interaction = result[1]

            modal.stop()

            modal_sent = True

        if not modal_sent:
            await interaction.response.defer(ephemeral=True)

        if last_event_id != self.bot.app.ledger.last_id():
            await sendable_interaction.send(
                "The register state has changed since you started this operation. Please try again.",
                ephemeral=True,
            )
            return

        entries, wait = await self.bot.app.ledger.append(
            OpenEvent(
                idempotency_key=str(interaction.id),
                type=EventsType.OPEN,
                source=EventsSource.DISCORD,
                cash_delta=total - excepted_total,
                discount=0,
                operator=interaction.user.id,
                occurred_at=interaction.created_at,
                cash_count=cash_count,
            )
        )

        await wait

        embed = nextcord.Embed(
            title=f"#{entries[0].id} Register Opened",
            description=f"Reported cash count by {interaction.user.mention}. Total cash: {total} yen.\nExpected total cash: {excepted_total} yen.\nDifference: {total - excepted_total} yen.",
            color=nextcord.Color.blue(),
        ).set_footer(text=f"open|{interaction.id}|{self.bot.app.conf['lease_label']}")

        [
            embed.add_field(
                name=f"{name.split('_')[1]} yen",
                value=f"{getattr(cash_count, name)} {'bill(s)' if name in ('yen_1000', 'yen_5000', 'yen_10000') else 'coin(s)'}",
                inline=True,
            )
            for name in CashCount.model_fields.keys()
        ]

        await sendable_interaction.send(
            "Successfully opened the register and reported cash count.",
            embed=embed,
            ephemeral=True,
        )

        await self.bot.send_log_channel(embed)

    @application_checks.guild_only()
    @slash_register.subcommand(name="x_report", description="Report operation X")
    async def slash_report_x(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int = SlashOption(
            name="yen_10000",
            description="Amount in 10,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_5000: int = SlashOption(
            name="yen_5000",
            description="Amount in 5,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_2000: int = SlashOption(
            name="yen_2000",
            description="Amount in 2,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_1000: int = SlashOption(
            name="yen_1000",
            description="Amount in 1,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_500: int = SlashOption(
            name="yen_500",
            description="Amount in 500 yen units",
            min_value=0,
            required=True,
        ),
        yen_100: int = SlashOption(
            name="yen_100",
            description="Amount in 100 yen units",
            min_value=0,
            required=True,
        ),
        yen_50: int = SlashOption(
            name="yen_50",
            description="Amount in 50 yen units",
            min_value=0,
            required=True,
        ),
        yen_10: int = SlashOption(
            name="yen_10",
            description="Amount in 10 yen units",
            min_value=0,
            required=True,
        ),
        yen_5: int = SlashOption(
            name="yen_5",
            description="Amount in 5 yen units",
            min_value=0,
            required=True,
        ),
        yen_1: int = SlashOption(
            name="yen_1",
            description="Amount in 1 yen units",
            min_value=0,
            required=True,
        ),
    ):
        if not self.bot.app.ledger.is_open():
            await interaction.send(
                "Cannot report cash count because the register is closed.",
                ephemeral=True,
            )
            return

        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        assert isinstance(interaction.channel, nextcord.TextChannel)

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
        modal_sent = False
        sendable_interaction: nextcord.Interaction = interaction

        last_event_id = self.bot.app.ledger.last_id()

        if total != excepted_total:
            modal = self.MismatchModal(
                bot=self.bot,
                idempotency_key=str(interaction.id),
                total=total,
                excepted_total=excepted_total,
                amount=cash_count,
                enable_adjust_button=False,
            )
            await interaction.response.send_modal(modal)
            try:
                result = await asyncio.wait_for(modal.result, timeout=120)
            except asyncio.TimeoutError:
                modal.stop()
                raise asyncio.TimeoutError("Modal interaction timed out.")

            if result[0] == "cancel":
                await result[1].send(
                    "Operation canceled due to cash count mismatch.",
                    ephemeral=True,
                )
                return
            sendable_interaction = result[1]

            modal.stop()

            modal_sent = True

        if not modal_sent:
            await interaction.response.defer(ephemeral=True)

        if last_event_id != self.bot.app.ledger.last_id():
            await sendable_interaction.send(
                "The register state has changed since you started this operation. Please try again.",
                ephemeral=True,
            )
            return

        entries, wait = await self.bot.app.ledger.append(
            CashCountEvent(
                idempotency_key=str(interaction.id),
                type=EventsType.X,
                source=EventsSource.DISCORD,
                cash_delta=0,
                discount=0,
                operator=interaction.user.id,
                occurred_at=interaction.created_at,
                cash_count=cash_count,
            ),
        )

        await wait

        embed = nextcord.Embed(
            title=f"#{entries[0].id} Cash Count Reported",
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

        await sendable_interaction.send(
            "Successfully reported cash count.",
            embed=embed,
            ephemeral=True,
        )

        await self.bot.send_log_channel(embed)

    @application_checks.guild_only()
    @slash_register.subcommand(name="close", description="Close the register")
    async def slash_close_register(
        self,
        interaction: nextcord.Interaction,
        yen_10000: int = SlashOption(
            name="yen_10000",
            description="Amount in 10,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_5000: int = SlashOption(
            name="yen_5000",
            description="Amount in 5,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_2000: int = SlashOption(
            name="yen_2000",
            description="Amount in 2,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_1000: int = SlashOption(
            name="yen_1000",
            description="Amount in 1,000 yen units",
            min_value=0,
            required=True,
        ),
        yen_500: int = SlashOption(
            name="yen_500",
            description="Amount in 500 yen units",
            min_value=0,
            required=True,
        ),
        yen_100: int = SlashOption(
            name="yen_100",
            description="Amount in 100 yen units",
            min_value=0,
            required=True,
        ),
        yen_50: int = SlashOption(
            name="yen_50",
            description="Amount in 50 yen units",
            min_value=0,
            required=True,
        ),
        yen_10: int = SlashOption(
            name="yen_10",
            description="Amount in 10 yen units",
            min_value=0,
            required=True,
        ),
        yen_5: int = SlashOption(
            name="yen_5",
            description="Amount in 5 yen units",
            min_value=0,
            required=True,
        ),
        yen_1: int = SlashOption(
            name="yen_1",
            description="Amount in 1 yen units",
            min_value=0,
            required=True,
        ),
    ):
        if not self.bot.app.ledger.is_open():
            await interaction.send(
                "Cannot report cash count because the register is closed.",
                ephemeral=True,
            )
            return

        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        assert isinstance(interaction.channel, nextcord.TextChannel)

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
        modal_sent = False
        sendable_interaction: nextcord.Interaction = interaction

        last_event_id = self.bot.app.ledger.last_id()

        if total != excepted_total:
            modal = self.MismatchModal(
                bot=self.bot,
                idempotency_key=str(interaction.id),
                total=total,
                excepted_total=excepted_total,
                amount=cash_count,
                enable_ignore_button=False,
            )
            await interaction.response.send_modal(modal)
            try:
                result = await asyncio.wait_for(modal.result, timeout=120)
            except asyncio.TimeoutError:
                modal.stop()
                raise asyncio.TimeoutError("Modal interaction timed out.")

            if result[0] == "cancel":
                await result[1].send(
                    "Operation canceled due to cash count mismatch.",
                    ephemeral=True,
                )
                return
            sendable_interaction = result[1]

            modal.stop()

            modal_sent = True

        if not modal_sent:
            await interaction.response.defer(ephemeral=True)

        if last_event_id != self.bot.app.ledger.last_id():
            await sendable_interaction.send(
                "The register state has changed since you started this operation. Please try again.",
                ephemeral=True,
            )
            return

        entries, wait = await self.bot.app.ledger.append(
            CloseEvent(
                idempotency_key=str(interaction.id),
                type=EventsType.CLOSE,
                source=EventsSource.DISCORD,
                cash_delta=total - excepted_total,
                discount=0,
                operator=interaction.user.id,
                occurred_at=interaction.created_at,
                cash_count=cash_count,
            ),
        )

        await wait

        embed = nextcord.Embed(
            title=f"#{entries[0].id} Register Closed",
            description=f"Reported cash count by {interaction.user.mention}. Total cash: {total} yen.\nExpected total cash: {excepted_total} yen.\nDifference: {total - excepted_total} yen.",
            color=nextcord.Color.blue(),
        ).set_footer(
            text=f"z_report|{interaction.id}|{self.bot.app.conf['lease_label']}"
        )

        [
            embed.add_field(
                name=f"{name.split('_')[1]} yen",
                value=f"{getattr(cash_count, name)} {'bill(s)' if name in ('yen_1000', 'yen_5000', 'yen_10000') else 'coin(s)'}",
                inline=True,
            )
            for name in CashCount.model_fields.keys()
        ]

        await sendable_interaction.send(
            "Successfully reported cash count.",
            embed=embed,
            ephemeral=True,
        )

        await self.bot.send_log_channel(embed)

    @get("/api/register/status")
    async def handle_register_status(self, request: Request) -> Response:
        password = request.headers.get("X-Auth-Password", "")

        if not self.bot.app.authenticator.check_password(password):
            return json_response({"error": "unauthorized"}, status=401)

        is_open = self.bot.app.ledger.is_open()
        cash_count = self.bot.app.ledger.get_cash_count()
        return json_response(
            {
                "is_open": is_open,
                "cash_count": cash_count.model_dump() if cash_count else None,
            }
        )


def setup(bot: BotApp):
    bot.add_cog(Register(bot))
