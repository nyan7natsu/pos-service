import asyncio
import datetime
import typing
from contextlib import asynccontextmanager
from logging import getLogger

import aiofiles

from .lock import NamedLock

if typing.TYPE_CHECKING:
    from ..bot import BotApp
    from ..model import (
        CashCount,
        CashCountEvent,
        CashInEvent,
        CashOutEvent,
        CloseEvent,
        LedgerEntry,
        LedgerEvent,
        OpenEvent,
        RefundEvent,
        SaleEvent,
        VoidEvent,
    )
    from ..pos import POSService

JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")


class LedgerManager:
    "Ledgerの管理クラス"

    def __init__(self, pos: "POSService", filename: str = "ledger.jsonl"):
        self.pos = pos
        self.logger = getLogger(f"{__name__}.lib.ledger")
        self.filename = filename

        self.data: list["LedgerEntry[LedgerEvent]"] = []

        self.__append_lock = NamedLock(name="ledger_append_lock")
        self.queue: asyncio.Queue[list["LedgerEntry[LedgerEvent]"]] = asyncio.Queue()

    @asynccontextmanager
    async def transaction(self):
        async with self.__append_lock:
            yield self.__append_lock

    async def append[E: "LedgerEvent"](self, *event: E) -> list[LedgerEntry[E]]:
        "Ledgerにイベントを追加する"
        async with self.transaction() as lock:
            return await self.append_with_unlock(lock, *event)

    async def append_with_unlock[E: "LedgerEvent"](
        self, lock: NamedLock, *event: E
    ) -> list[LedgerEntry[E]]:
        "Ledgerにイベントを追加する（ロックを取得せずに呼び出す）"

        if lock.name != self.__append_lock.name or not lock.locked():
            raise RuntimeError("Lock is not acquired")

        entries: list[LedgerEntry[E]] = []
        for e in event:
            entry = LedgerEntry(
                id=self.last_id() + 1,
                recorded_at=datetime.datetime.now().astimezone(JST).isoformat(),
                **e.model_dump(),
            )
            entries.append(entry)
            self.data.append(entry)
        await self.queue.put(entries)
        return entries

    async def __write_file(self, events: list["LedgerEntry[LedgerEvent]"]):
        async with aiofiles.open(self.filename, mode="a") as f:
            await f.write(
                "\n".join([event.model_dump_json() for event in events]) + "\n"
            )

    async def run(self):
        "Ledgerのイベントを処理する"
        while True:
            entry = await self.queue.get()
            try:
                await self.__write_file(entry)
            except Exception as e:
                self.logger.error(f"Failed to write ledger entry: {e}")
            finally:
                self.queue.task_done()

    async def load(self):
        "Ledgerのイベントを読み込む"
        try:
            async with aiofiles.open(self.filename, mode="r") as f:
                async for line in f:
                    entry = LedgerEntry.model_validate_json(line.strip())
                    self.data.append(entry)
        except FileNotFoundError:
            self.logger.warning(
                f"Ledger file {self.filename} not found. Starting with empty ledger."
            )
        except Exception as e:
            self.logger.error(f"Failed to load ledger: {e}")

    def find(self, *, idempotency_key: str) -> "LedgerEntry[LedgerEvent] | None":
        "Ledgerのイベントを冪等キーから検索する"
        for entry in self.data:
            if entry.event.idempotency_key == idempotency_key:
                return entry
        return None

    async def wait_saved(self, *, id: str):
        "Ledgerのイベントが保存されるまで待つ"
        while True:
            if any(event.id == id for event in self.data):
                return
            await asyncio.sleep(0.1)

    def get(self, *, id: int) -> "LedgerEntry[LedgerEvent] | None":
        "LedgerのイベントをIDから取得する"
        for event in self.data:
            if event.id == id:
                return event
        return None

    def after(self, *, id: int) -> list["LedgerEntry[LedgerEvent]"]:
        "LedgerのイベントをID以降で取得する"
        for idx, event in enumerate(self.data):
            if event.id == id:
                return self.data[idx + 1 :]
        return []

    def expected_cash(self) -> int:
        "Ledgerのイベントから期待される現金残高を計算する"
        cash = 0
        for entry in self.data:
            cash += entry.event.cash_delta
        return cash

    def is_open(self) -> bool:
        "Ledgerのイベントからレジが開いているかを判定する"
        for entry in reversed(self.data):
            match entry.event:
                case OpenEvent():
                    return True
                case CloseEvent():
                    return False
        return False

    def last_id(self) -> int:
        "Ledgerのイベントから最後のIDを取得する"
        return self.data[-1].id if self.data else 0

    def get_cash_count(self) -> CashCount:
        "LedgerのイベントからOpenEventまたはCloseEventのCashCountを取得する"
        for entry in reversed(self.data):
            match entry.event:
                case (
                    OpenEvent(cash_count=cash_count)
                    | CloseEvent(cash_count=cash_count)
                    | CashCountEvent(cash_count=cash_count)
                ):
                    return cash_count
        return CashCount(
            yen_10000=0,
            yen_5000=0,
            yen_2000=0,
            yen_1000=0,
            yen_500=0,
            yen_100=0,
            yen_50=0,
            yen_10=0,
            yen_5=0,
            yen_1=0,
        )

    def current_boundary(self) -> int:
        "Ledgerのイベントから最後の締めIDを取得する．指定された会計が締め済みかどうかの判定などに使えます"
        for entry in reversed(self.data):
            match entry.event:
                case CloseEvent():
                    return entry.id
        return 0
