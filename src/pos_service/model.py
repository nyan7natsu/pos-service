import datetime
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
    recorded_at: datetime.datetime
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
    occurred_at: datetime.datetime


class CashEventBase(LedgerEventBase):
    cash_count: "CashCount"

    @pydantic.model_validator(mode="after")
    def check_cash_count(self):
        if self.cash_count.total() != self.cash_delta:
            raise ValueError(
                f"cash_count の合計 {self.cash_count.total()} が cash_delta {self.cash_delta} と違う")
        return self


class SaleEvent(CashEventBase):
    type: typing.Literal[EventsType.SALE] = EventsType.SALE
    items: tuple["SaleItem", ...]


class SaleItem(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    product_id: int
    quantity: int = pydantic.Field(gt=0)
    unit_price: int = pydantic.Field(gt=0)


class RefundItem(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(frozen=True, extra="forbid")
    product_id: int
    quantity: int = pydantic.Field(lt=0)
    unit_price: int = pydantic.Field(gt=0)


class VoidEvent(CashEventBase):
    type: typing.Literal[EventsType.VOID] = EventsType.VOID
    reason: str
    ref_event_id: int


class RefundEvent(CashEventBase):
    type: typing.Literal[EventsType.REFUND] = EventsType.REFUND
    reason: str
    items: tuple["RefundItem", ...]


class CashInEvent(CashEventBase):
    type: typing.Literal[EventsType.CASH_IN] = EventsType.CASH_IN


class CashOutEvent(CashEventBase):
    type: typing.Literal[EventsType.CASH_OUT] = EventsType.CASH_OUT


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
    yen_10000: int = 0
    yen_5000: int = 0
    yen_2000: int = 0
    yen_1000: int = 0
    yen_500: int = 0
    yen_100: int = 0
    yen_50: int = 0
    yen_10: int = 0
    yen_5: int = 0
    yen_1: int = 0

    def __add__(self, other: "CashCount") -> "CashCount":
        return CashCount(
            yen_10000=self.yen_10000 + other.yen_10000,
            yen_5000=self.yen_5000 + other.yen_5000,
            yen_2000=self.yen_2000 + other.yen_2000,
            yen_1000=self.yen_1000 + other.yen_1000,
            yen_500=self.yen_500 + other.yen_500,
            yen_100=self.yen_100 + other.yen_100,
            yen_50=self.yen_50 + other.yen_50,
            yen_10=self.yen_10 + other.yen_10,
            yen_5=self.yen_5 + other.yen_5,
            yen_1=self.yen_1 + other.yen_1,
        )

    def __neg__(self) -> "CashCount":
        return CashCount(
            yen_10000=-self.yen_10000,
            yen_5000=-self.yen_5000,
            yen_2000=-self.yen_2000,
            yen_1000=-self.yen_1000,
            yen_500=-self.yen_500,
            yen_100=-self.yen_100,
            yen_50=-self.yen_50,
            yen_10=-self.yen_10,
            yen_5=-self.yen_5,
            yen_1=-self.yen_1,
        )

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
