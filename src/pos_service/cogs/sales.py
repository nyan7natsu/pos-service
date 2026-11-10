import datetime
import typing
from logging import getLogger

import nextcord
import pydantic
from aiohttp.web import Request, Response, json_response
from nextcord.ext import application_checks, commands

from ..bot import BotApp
from ..model import (CashCount, EventsSource, EventsType, LedgerEntry,
                     LedgerEvent, SaleEvent, SaleItem, VoidEvent)
from ..webutil import WebCog, get, post

_logger = getLogger(__name__)


class SaleData(pydantic.BaseModel):
    idempotency_key: str = pydantic.Field(min_length=1, max_length=255)
    items: tuple[SaleItem, ...] = pydantic.Field(min_length=1)
    discount: int = pydantic.Field(ge=0)
    cash_count: "CashCount"
    occurred_at: datetime.datetime

    @pydantic.model_validator(mode="after")
    def check_discount(self) -> "SaleData":
        subtotal = sum(i.quantity * i.unit_price for i in self.items)
        if self.discount > subtotal:
            raise ValueError("値引きが小計を超えています")
        return self

    @pydantic.model_validator(mode="after")
    def check_cash_count(self) -> "SaleData":
        total = sum(i.quantity * i.unit_price for i in self.items) - \
            self.discount
        if self.cash_count.total() != total:
            raise ValueError(
                f"現金計算の合計が小計と一致しません: {self.cash_count.total()} != {total}"
            )
        return self


class VoidError(Exception):
    "VOIDできないことを表す例外"

class Sales(WebCog):

    class VoidModal(nextcord.ui.Modal):
        def __init__(
            self,
            parent: "Sales",
            idempotency_key: str,
            message: nextcord.Message,
            interaction_id: int,
        ):
            super().__init__(title="VOID確認")
            self.parent = parent
            self.idempotency_key = idempotency_key
            self.message = message
            self.interaction_id = interaction_id

            self.input = nextcord.ui.TextInput(
                label="VOID理由",
                placeholder="VOID理由を入力してください",
                style=nextcord.TextInputStyle.paragraph,
                required=True,
                max_length=200,
            )
            self.add_item(self.input)

        async def callback(self, interaction: nextcord.Interaction):
            await interaction.response.defer(ephemeral=True, with_message=True)
            reason = self.input.value
            if reason is None or reason.strip() == "":
                await interaction.send("VOID理由を入力してください", ephemeral=True)
                return

            assert isinstance(interaction.user, nextcord.User | nextcord.Member)

            try:
                void = await self.parent._void(
                    self.idempotency_key,
                    interaction.user.id,
                    str(self.interaction_id),
                    reason,
                    interaction.created_at,
                )
            except VoidError as e:
                await interaction.send(f"VOIDできません: {e}", ephemeral=True)
                return

            await interaction.send(
                f"VOIDしました。レシート番号: {void.ref_event_id}", ephemeral=True
            )
            embed = self.message.embeds[0]
            embed.title = f"[VOIDED] {embed.title}"
            embed.color = nextcord.Color.yellow()
            embed.add_field(name="VOID理由", value=reason, inline=False)
            embed.add_field(
                name="VOIDユーザー", value=interaction.user.mention, inline=False
            )
            embed.set_footer(text=f"voided|{self.idempotency_key}")
            await self.message.edit(embed=embed)

    async def _get_voidable(self, target_key: str) -> LedgerEntry[SaleEvent]:
        "指定されたレシート番号の会計がVOID可能かどうかを確認し、可能ならそのLedgerEntryを返す。VOID不可ならVoidErrorを投げる"
        if not self.bot.app.ledger.is_open():
            raise VoidError("開局していません")
        target = self.bot.app.ledger.find(idempotency_key=target_key)
        if target is None:
            raise VoidError("対象の会計が見つかりません")
        if target.event.type != EventsType.SALE:
            raise VoidError("売上以外はVOIDできません")
        if not isinstance(target.event, SaleEvent):
            raise VoidError("売上以外はVOIDできません")

        target = typing.cast(
            LedgerEntry[SaleEvent], target
        )  # 前項までで型が保証されているのでキャストする

        if target.id <= self.bot.app.ledger.current_boundary():
            raise VoidError("締め済みの会計です。レジマイナスで処理してください")

        if [
            e
            for e in self.bot.app.ledger.after(
                id=self.bot.app.ledger.current_boundary()
            )
            if isinstance(e.event, VoidEvent) and e.event.ref_event_id == target.id
        ]:
            raise VoidError("すでにVOID済みです")
        return target

    async def _void(
        self,
        target_key: str,
        operator: int,
        idempotency_key: str,
        reason: str,
        occurred_at: datetime.datetime,
    ) -> VoidEvent:
        # 同じ操作の再送なら、前回の結果を返す
        existing = self.bot.app.ledger.find(idempotency_key=idempotency_key)
        if existing:
            if not isinstance(existing.event, VoidEvent):
                raise RuntimeError("既存のイベントがVOIDイベントではありません")
            return existing.event

        async with self.bot.app.ledger.transaction() as lock:
            target = await self._get_voidable(target_key)

            void = VoidEvent(
                idempotency_key=idempotency_key,
                type=EventsType.VOID,
                source=EventsSource.DISCORD,
                cash_delta=-target.event.cash_delta,
                discount=target.event.discount,
                operator=operator,
                ref_event_id=target.id,
                occurred_at=occurred_at,
                reason=reason,
                cash_count=-target.event.cash_count,
            )

            await (await self.bot.app.ledger.append_with_unlock(lock, void))[1]

        return void

    @application_checks.guild_only()
    @nextcord.message_command(name="void")
    async def void_message_command(
        self, interaction: nextcord.Interaction, message: nextcord.Message
    ):
        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        assert isinstance(self.bot.user, nextcord.User | nextcord.Member)

        if message.author.id != self.bot.user.id:
            await interaction.send(
                "このメッセージはこのボットが送信したものではありません。",
                ephemeral=True,
            )
            return

        if (
            not message.embeds
            or not message.embeds[0].footer.text
            or not message.embeds[0].footer.text.startswith("sale_processed|")
        ):
            await interaction.send(
                "このメッセージは販売処理のメッセージではありません。",
                ephemeral=True,
            )
            return

        idempotency_key = message.embeds[0].footer.text.split("|")[1]

        await interaction.response.send_modal(
            self.VoidModal(self, idempotency_key, message, interaction.id)
        )

    @get("/api/products")
    async def handle_get_products(self, _: Request) -> Response:
        products = self.bot.app.product_manager.products
        return json_response({"products": [p.model_dump() for p in products]})

    @post("/api/sale")
    async def handle_sale(self, request: Request) -> Response:
        password = request.headers.get("X-Auth-Password", "")

        if not self.bot.app.authenticator.check_password(password):
            return json_response({"error": "unauthorized"}, status=401)

        try:
            sale_data = SaleData.model_validate_json(await request.text())
        except pydantic.ValidationError as e:
            _logger.warning("Invalid sale data: %s", e)
            return Response(
                text=e.json(include_url=False),
                status=422,
                content_type="application/json",
            )

        # 再送なら、前回の結果をそのまま返す
        existing = self.bot.app.ledger.find(idempotency_key=sale_data.idempotency_key)
        if existing:
            await self.bot.app.ledger.wait_saved(ids=[existing.id])
            return json_response({"receipt_id": existing.id})

        if not self.bot.app.ledger.is_open():
            return json_response({"error": "register closed"}, status=409)

        for item in sale_data.items:
            product = self.bot.app.product_manager.get_product(item.product_id)
            if product is None:
                return json_response(
                    {"error": f"unknown product {item.product_id}"}, status=422
                )
            if product.price != item.unit_price:
                _logger.warning(
                    "Price mismatch: #%s %s != %s",
                    item.product_id,
                    item.unit_price,
                    product.price,
                )

        total = (
            sum(i.quantity * i.unit_price for i in sale_data.items) - sale_data.discount
        )

        async with self.bot.app.ledger.transaction() as lock:
            # 一応もう一回チェック
            if not self.bot.app.ledger.is_open():
                return json_response({"error": "register closed"}, status=409)

            if existing := self.bot.app.ledger.find(
                idempotency_key=sale_data.idempotency_key
            ):
                receipt_id = existing.id
                wait = self.bot.app.ledger.wait_saved(ids=[existing.id])
                new_entry = None

            else:
                entry, wait = await self.bot.app.ledger.append_with_unlock(
                    lock,
                    SaleEvent(
                        idempotency_key=sale_data.idempotency_key,
                        type=EventsType.SALE,
                        source=EventsSource.POS,
                        cash_delta=total,
                        discount=sale_data.discount,
                        occurred_at=sale_data.occurred_at,
                        operator=0,
                        items=sale_data.items,
                        cash_count=sale_data.cash_count,
                    )
                )
                new_entry = entry[0]
                receipt_id = entry[0].id

        await wait

        if new_entry:
            _logger.info(
                "Sale processed: #%s %s",
                receipt_id, new_entry.event.idempotency_key
            )
            self.bot.dispatch("sale_processed", new_entry)
        return json_response({"receipt_id": receipt_id})


def setup(bot: BotApp):
    bot.add_cog(Sales(bot))
