import datetime
import typing
from logging import getLogger

import nextcord
import pydantic
from aiohttp.web import Request, Response, json_response
from nextcord.ext import application_checks, commands

from ..bot import BotApp
from ..lib.ledger import JST
from ..model import (CashCount, EventsSource, EventsType, LedgerEntry,
                     SaleEvent, SaleItem, VoidEvent)
from ..webutil import WebCog, get, post

_logger = getLogger(__name__)

if typing.TYPE_CHECKING:
    from .backstage import BackStage


class SaleData(pydantic.BaseModel):
    idempotency_key: str = pydantic.Field(min_length=1, max_length=255)
    items: tuple[SaleItem, ...] = pydantic.Field(min_length=1)
    discount: int = pydantic.Field(ge=0)
    cash_count: "CashCount"
    occurred_at: pydantic.AwareDatetime
    operator: str = pydantic.Field(min_length=1, max_length=255)

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
    def __init__(self, bot: BotApp):
        super().__init__(bot)
        self.operators: list[tuple[str, int]] = []

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.operators = await self.get_users_from_role_id(
                self.bot.app.conf["operator_role_id"]
            )
        except Exception as e:
            self.logger.error("Failed to get operators: %s", e)
            self.operators = []

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
                    EventsSource.DISCORD,
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
            embed.title = f"{embed.title} [VOIDED]"
            embed.color = nextcord.Color.dark_gray()
            embed.add_field(name="VOID理由", value=reason, inline=False)
            embed.add_field(
                name="VOIDユーザー", value=interaction.user.mention, inline=False
            )
            embed.set_footer(
                text=f"voided|{self.idempotency_key}|{self.parent.bot.app.conf['lease_label']}"
            )
            await self.message.edit(embed=embed)

    def sale_log(self, entry: LedgerEntry[SaleEvent]):
        user = self.bot.get_user(entry.event.operator)
        embed = (
            nextcord.Embed(
                title=f"#{entry.id} Sale",
                description=f"Sale processed successfully.\n"
                + "\n".join(
                    [
                        f"**{i.name if (i := self.bot.app.product_manager.get_product(item.product_id)) else item.product_id}** @ ¥{item.unit_price}x{item.quantity} (¥{item.unit_price * item.quantity})"
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
        if user:
            embed.set_author(
                name=user.display_name,
                icon_url=user.display_avatar.url
            )
        else:
            embed.set_author(
                name=f"Operator ID: {entry.event.operator} (not found)",
            )

        self.bot.create_report_task("", embed=embed)

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
        source: EventsSource,
        target_key: str,
        operator: int,
        idempotency_key: str,
        reason: str,
        occurred_at: datetime.datetime,
        message: nextcord.Message | None = None,
    ) -> VoidEvent:
        # 同じ操作の再送なら、前回の結果を返す
        existing = self.bot.app.ledger.find(idempotency_key=idempotency_key)
        if existing:
            if not isinstance(existing.event, VoidEvent):
                raise RuntimeError("既存のイベントがVOIDイベントではありません")
            wait = self.bot.app.ledger.wait_saved(ids=[existing.id])
            await wait
            return existing.event

        async with self.bot.app.ledger.transaction() as lock:
            target = await self._get_voidable(target_key)

            void = VoidEvent(
                idempotency_key=idempotency_key,
                type=EventsType.VOID,
                source=source,
                cash_delta=-target.event.cash_delta,
                discount=target.event.discount,
                operator=operator,
                ref_event_id=target.id,
                occurred_at=occurred_at,
                reason=reason,
                cash_count=-target.event.cash_count,
            )

            entries, wait = await self.bot.app.ledger.append_with_unlock(lock, void)
        await wait

        if not message:
            report_channel = await self.bot.resolve_channel(self.bot.app.conf["report_channel_id"])
            if isinstance(report_channel, nextcord.TextChannel):
                async for message in report_channel.history(limit=100):
                    if (
                        message.embeds
                        and message.embeds[0].footer
                        and message.embeds[0].footer.text
                        and message.embeds[0].footer.text.startswith(
                            f"sale_processed|{target.event.idempotency_key}|"
                        )
                    ):
                        embed = message.embeds[0]
                        embed.title = f"{embed.title} [VOIDED]"
                        embed.color = nextcord.Color.dark_gray()
                        embed.add_field(
                            name="VOID理由", value=reason, inline=False)
                        embed.add_field(
                            name="VOIDユーザー", value=f"<@{operator}>", inline=False
                        )
                        embed.set_footer(
                            text=f"voided|{idempotency_key}|{self.bot.app.conf['lease_label']}"
                        )
                        await message.edit(embed=embed)

        embed = nextcord.Embed(
            title=f"#{entries[0].id} VOID",
            description=f"VOID processed successfully for sale #{target.id}.",
            color=nextcord.Color.yellow(),
        ).add_field(name="VOID理由", value=reason, inline=False).add_field(
            name="VOIDユーザー", value=f"<@{operator}>", inline=False
        ).set_footer(
            text=f"voided|{idempotency_key}|{self.bot.app.conf['lease_label']}"
        )
        self.bot.create_report_task("", embed)

        return void

    @get("/api/backstage/sales")
    async def handle_get_sales(self, request: Request) -> Response:
        "販売処理の一覧を返すAPIエンドポイント"
        cog: "BackStage | None" = self.bot.get_cog("BackStage")  # type: ignore
        if cog is None:
            return json_response({"error": "backstage not loaded"}, status=500)

        if not cog.is_session_valid(request):
            return json_response({"error": "unauthorized"}, status=401)

        entries = self.bot.app.ledger.after(
            id=self.bot.app.ledger.current_boundary())
        sales = [
            e for e in entries
            if isinstance(e.event, SaleEvent)
        ]
        voided = {
            e.event.ref_event_id for e in entries if isinstance(e.event, VoidEvent)
        }
        return json_response(
            {"sales": [e.model_dump(
                mode="json",
                context={"api": True}
            ) | {"voided": e.id in voided} for e in sales]},
            status=200
        )

    @get("/api/backstage/items")
    async def handle_get_items(self, request: Request) -> Response:
        "販売処理の一覧から，すでに販売された商品における材料の各種数量を返すAPIエンドポイント"

        cog: "BackStage | None" = self.bot.get_cog("BackStage")  # type: ignore
        if cog is None:
            return json_response({"error": "backstage not loaded"}, status=500)

        if not cog.is_session_valid(request):
            return json_response({"error": "unauthorized"}, status=401)

        entries = self.bot.app.ledger.after(id=0)
        sales: list[LedgerEntry[SaleEvent]] = [
            e for e in entries
            if isinstance(e.event, SaleEvent)
        ]  # type: ignore
        voided = {
            e.event.ref_event_id for e in entries if isinstance(e.event, VoidEvent)
        }

        item_counts: dict[str, int] = {}
        for sale in sales:
            if sale.id in voided:
                continue
            for item in sale.event.items:
                product = self.bot.app.product_manager.get_product(
                    item.product_id
                )
                if not product:
                    _logger.warning(
                        "Product not found for sale item: %s", item.product_id)
                    continue
                for product_item in product.items:
                    item_counts[product_item.product_name] = item_counts.get(
                        product_item.product_name, 0
                    ) + product_item.quantity * item.quantity

        return json_response({"item_counts": item_counts}, status=200)


    @post("/api/backstage/void")
    async def handle_void(self, request: Request) -> Response:
        "VOID処理を行うAPIエンドポイント。VOID処理の結果としてVOIDイベントのIDを返す。再送の場合は前回の結果を返す。"

        cog: "BackStage | None" = self.bot.get_cog("BackStage")  # type: ignore
        if cog is None:
            return json_response({"error": "backstage not loaded"}, status=500)

        if not cog.is_session_valid(request):
            return json_response({"error": "unauthorized"}, status=401)

        try:
            data = await request.json()
            target_key = data["target_key"]
            operator = cog.get_session_data(request)
            if operator is None:
                return json_response({"error": "unauthorized"}, status=401)
            idempotency_key = data["idempotency_key"]
            reason = data["reason"]
            occurred_at = datetime.datetime.now(tz=JST)
        except Exception as e:
            _logger.warning("Invalid void data: %s", e)
            return json_response({"error": "invalid request", "detail": str(e)}, status=422)

        try:
            void_event = await self._void(
                EventsSource.BACKSTAGE,
                target_key,
                operator[0],
                idempotency_key,
                reason,
                occurred_at
            )
        except VoidError as e:
            return json_response({"error": str(e)}, status=409)

        return json_response({"void_event_id": void_event.ref_event_id})

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

    async def get_users_from_role_id(self, role_id: int) -> list[tuple[str, int]]:
        guild_id = self.bot.app.conf["guild_ids"][0]
        guild = self.bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except nextcord.NotFound:
                raise RuntimeError("ギルドが見つかりません")
        if not guild:
            raise RuntimeError("ギルドが見つかりません")

        role = guild.get_role(role_id)
        if not role:
            try:
                role = await guild.fetch_role(role_id)
            except nextcord.NotFound:
                raise RuntimeError("ロールが見つかりません")
        if not role:
            raise RuntimeError("ロールが見つかりません")
        return [(member.display_name, member.id) for member in role.members]

    @nextcord.slash_command(name="operators")
    async def slash_operators(self, interaction: nextcord.Interaction): ...

    @application_checks.guild_only()
    @slash_operators.subcommand(
        name="update", description="Update the list of operators"
    )
    async def slash_operators_update(
        self,
        interaction: nextcord.Interaction,
        operator_role: nextcord.Role = nextcord.SlashOption(
            name="operator_role",
            description="The role that represents operators",
            required=True,
        )
    ):
        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        self.operators = await self.get_users_from_role_id(operator_role.id)
        await interaction.send(
            "Operators updated.\n**Only in this session**. To make it permanent, please update the operator role in the guild or change the bot configuration.",
            embed=nextcord.Embed(
                title="Current Operators",
                description="\n".join([
                    f"- <@{user_id}>" for _,
                    user_id in self.operators
                ]),
                color=nextcord.Color.green(),
            ).set_footer(text=f"operators_updated|{interaction.id}|{self.bot.app.conf['lease_label']}"),
            ephemeral=True,
        )

    @application_checks.guild_only()
    @slash_operators.subcommand(
        name="list", description="List the current operators"
    )
    async def slash_operators_list(self, interaction: nextcord.Interaction):
        assert isinstance(interaction.user, nextcord.User | nextcord.Member)
        if not self.operators:
            await interaction.send("No operators set.", ephemeral=True)
            return
        await interaction.send(
            embed=nextcord.Embed(
                title="Current Operators",
                description="\n".join([
                    f"- <@{user_id}>" for _,
                    user_id in self.operators
                ]),
                color=nextcord.Color.blue(),
            ).set_footer(text=f"operators_list|{interaction.id}|{self.bot.app.conf['lease_label']}"),
            ephemeral=True,
        )

    @get("/api/register/operators")
    async def handle_get_operators(self, request: Request) -> Response:
        "レジを操作する事ができる担当者の，一覧を返すAPIエンドポイント"
        if not self.bot.app.authenticator.check_request(request):
            return json_response({"error": "unauthorized"}, status=401)

        return json_response({"operators": [{"name": name, "id": str(user_id)} for name, user_id in self.operators]})

    @get("/api/register/products")
    async def handle_get_products(self, request: Request) -> Response:
        "販売可能な商品の一覧を返すAPIエンドポイント"
        cog: "BackStage | None" = self.bot.get_cog("BackStage")  # type: ignore

        if not self.bot.app.authenticator.check_request(request) and (cog is None or not cog.is_session_valid(request)):
            return json_response({"error": "unauthorized"}, status=401)

        products = self.bot.app.product_manager.products
        return json_response({"products": [p.model_dump() for p in products if p.enabled]})


    @post("/api/register/sale")
    async def handle_sale(self, request: Request) -> Response:
        "販売処理を行うAPIエンドポイント。販売処理の結果としてレシート番号を返す。再送の場合は前回の結果を返す。"
        if not self.bot.app.authenticator.check_request(request):
            return json_response({"error": "unauthorized"}, status=401)

        try:
            sale_data = SaleData.model_validate_json(await request.text())
        except pydantic.ValidationError as e:
            _logger.warning("Invalid sale data: %s", e)
            return json_response({"error": "invalid request", "detail": e.errors(include_url=False, include_context=False)}, status=422)

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
                ops = [
                    user_id for _, user_id in self.operators if str(user_id) == sale_data.operator
                ]
                op = ops[0] if ops else 0
                if op == 0:
                    _logger.warning(
                        "Unknown operator: %s",
                        sale_data.operator
                    )
                entry, wait = await self.bot.app.ledger.append_with_unlock(
                    lock,
                    SaleEvent(
                        idempotency_key=sale_data.idempotency_key,
                        type=EventsType.SALE,
                        source=EventsSource.POS,
                        cash_delta=total,
                        discount=sale_data.discount,
                        occurred_at=sale_data.occurred_at,
                        operator=op,
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
            self.sale_log(new_entry)

        return json_response({"receipt_id": receipt_id})


def setup(bot: BotApp):
    bot.add_cog(Sales(bot))
