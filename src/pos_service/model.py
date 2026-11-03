import typing
from enum import Enum

import pydantic


class EventsType(str, Enum):
    SALE = "sale"
    VOID = "void"
    REFUND = "refund"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    OPEN = "open"
    CLOSE = "close"
    X = "x"


class EventsSource(str, Enum):
    POS = "pos"
    DISCORD = "discord"
    OTHER = "other"


class LedgerEntry[T: "LedgerEvent"](pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    id: int
    recorded_at: str
    event: "T"


class LedgerEventBase(pydantic.BaseModel):
    "Ledgerのイベントの基本クラス"

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str
    "イベントの冪等キー。レシート番号やVOIDの参照先など、イベントを一意に識別するための文字列"

    source: EventsSource
    cash_delta: int
    discount: int
    operator: int
    occurred_at: str


class SaleEvent(LedgerEventBase):
    type: typing.Literal[EventsType.SALE] = EventsType.SALE
    items: tuple["SaleItem"]


class SaleItem(pydantic.BaseModel):
    product_id: int
    quantity: int = pydantic.Field(gt=0)
    unit_price: int = pydantic.Field(gt=0)


class VoidEvent(LedgerEventBase):
    type: typing.Literal[EventsType.VOID] = EventsType.VOID
    reason: str
    ref_event_id: int


class RefundEvent(LedgerEventBase):
    type: typing.Literal[EventsType.REFUND] = EventsType.REFUND
    reason: str
    ref_event_id: int


class CashInEvent(LedgerEventBase):
    type: typing.Literal[EventsType.CASH_IN] = EventsType.CASH_IN
    cash_count: "CashCount"


class CashOutEvent(LedgerEventBase):
    type: typing.Literal[EventsType.CASH_OUT] = EventsType.CASH_OUT
    cash_count: "CashCount"


class OpenEvent(LedgerEventBase):
    type: typing.Literal[EventsType.OPEN] = EventsType.OPEN
    cash_count: "CashCount"


class CloseEvent(LedgerEventBase):
    type: typing.Literal[EventsType.CLOSE] = EventsType.CLOSE
    cash_count: "CashCount"


class CashCountEvent(LedgerEventBase):
    type: typing.Literal[EventsType.X] = EventsType.X
    cash_count: "CashCount"


class CashCount(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    yen_10000: int | None
    yen_5000: int | None
    yen_2000: int | None
    yen_1000: int | None
    yen_500: int | None
    yen_100: int | None
    yen_50: int | None
    yen_10: int | None
    yen_5: int | None
    yen_1: int | None

    def total(self) -> int:
        return (
            (self.yen_10000 or 0) * 10000
            + (self.yen_5000 or 0) * 5000
            + (self.yen_2000 or 0) * 2000
            + (self.yen_1000 or 0) * 1000
            + (self.yen_500 or 0) * 500
            + (self.yen_100 or 0) * 100
            + (self.yen_50 or 0) * 50
            + (self.yen_10 or 0) * 10
            + (self.yen_5 or 0) * 5
            + (self.yen_1 or 0) * 1
        )

    def is_only_positive(self) -> bool:
        return all(
            (getattr(self, field) is None or getattr(self, field) >= 0)
            for field in CashCount.model_fields.keys()
        )

    def is_only_negative(self) -> bool:
        return all(
            (getattr(self, field) is None or getattr(self, field) <= 0)
            for field in CashCount.model_fields.keys()
        )


LedgerEvent = typing.Annotated[
    typing.Union[
        SaleEvent,
        VoidEvent,
        RefundEvent,
        CashInEvent,
        CashOutEvent,
        OpenEvent,
        CloseEvent,
        CashCountEvent,
    ],
    pydantic.Field(discriminator="type"),
]
