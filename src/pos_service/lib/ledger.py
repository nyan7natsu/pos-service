import asyncio
import datetime
import os
import typing
from contextlib import asynccontextmanager
from logging import getLogger

import aiofiles

from ..model import (CashCount, CashCountEvent, CashInEvent, CashOutEvent,
                     CloseEvent, LedgerEntry, LedgerEvent, OpenEvent,
                     RefundEvent, SaleEvent, VoidEvent)
from .lock import NamedLock

if typing.TYPE_CHECKING:
    from ..bot import BotApp
    from ..pos import POSService

JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")


class LedgerManager:
    "Ledgerの管理クラス"

    def __init__(self, pos: "POSService", filename: str = "ledger.jsonl"):
        self.pos = pos
        self.logger = getLogger(f"{__name__}.lib.ledger")
        self.filename = filename
        self.write_failed: bool = False

        self.data: list["LedgerEntry[LedgerEvent]"] = []

        self.__append_lock = NamedLock(name="ledger_append_lock")
        self.queue: asyncio.Queue[list["LedgerEntry[LedgerEvent]"]] = asyncio.Queue()
        self.wrote: list[int] = []
        self.exception: dict[int, Exception] = {}

    @asynccontextmanager
    async def transaction(self):
        async with self.__append_lock:
            yield self.__append_lock

    async def append[E: "LedgerEvent"](
        self, *event: E
    ) -> tuple[list["LedgerEntry[E]"], typing.Coroutine[typing.Any, typing.Any, None]]:
        "Ledgerにイベントを追加する"
        async with self.transaction() as lock:
            return await self.append_with_unlock(lock, *event)

    async def append_with_unlock[E: "LedgerEvent"](
        self, lock: NamedLock, *event: E
    ) -> tuple[list[LedgerEntry[E]], typing.Coroutine[typing.Any, typing.Any, None]]:
        "Ledgerにイベントを追加する（ロックを取得せずに呼び出す）"

        if lock.name != self.__append_lock.name or not lock.locked():
            raise RuntimeError("Lock is not acquired")

        entries: list[LedgerEntry[E]] = []
        for e in event:
            if self.find(idempotency_key=e.idempotency_key):
                raise RuntimeError(
                    f"Duplicate idempotency key: {e.idempotency_key}")
            entry = LedgerEntry(
                id=self.last_id() + 1,
                recorded_at=datetime.datetime.now().astimezone(JST),
                event=e,
            )
            entries.append(entry)
            self.data.append(entry)
        await self.queue.put(entries)

        return (entries, self.wait_saved(ids=[e.id for e in entries]))

    async def __write_file(self, events: list["LedgerEntry[LedgerEvent]"]):
        async with aiofiles.open(self.filename, mode="a", encoding="utf-8") as f:
            await f.write(
                "\n".join([event.model_dump_json() for event in events]) + "\n"
            )
            await f.flush()
            await asyncio.to_thread(os.fsync, f.fileno())

    async def run(self):
        "Ledgerのイベントを処理する"
        while True:
            entry = await self.queue.get()
            try:
                if self.write_failed:
                    continue
                await self.__write_file(entry)
                self.wrote.extend([e.id for e in entry])
            except Exception as err:
                self.logger.error(f"Failed to write ledger entry: {err}")
                self.exception.update({e.id: err for e in entry})
                self.write_failed = True
            finally:
                self.queue.task_done()

    async def load(self):
        "Ledgerのイベントを読み込む"
        data: list["LedgerEntry[LedgerEvent]"] = []
        self.logger.info(f"Loading ledger from {self.filename}...")
        try:
            async with aiofiles.open(self.filename, mode="rb") as f:
                raw = await f.read()

            complete, sep, torn = raw.rpartition(b"\n")

            if torn:
                self.logger.warning(
                    "Discarding incomplete last line: %r", torn)
                async with aiofiles.open(self.filename, "r+b") as f:
                    await f.truncate(len(complete) + len(sep))
                    await f.flush()
                    await asyncio.to_thread(os.fsync, f.fileno())

            for line in complete.split(b"\n"):
                if not line.strip():
                    continue
                entry = LedgerEntry.model_validate_json(line)
                data.append(entry)

        except FileNotFoundError:
            self.logger.warning(
                f"Ledger file {self.filename} not found. Creating a new one."
            )
            async with aiofiles.open(self.filename, mode="w", encoding="utf-8") as f:
                await f.write("")

        self.logger.info(f"Checking ledger consistency...")

        for i, entry in enumerate(data):
            if entry.id != i + 1:
                self.logger.error(
                    f"Ledger entry ID mismatch: expected {i + 1}, got {entry.id}"
                )
                self.pos.request_stop()
                raise RuntimeError(
                    f"Ledger entry ID mismatch: expected {i + 1}, got {entry.id}"
                )

        self.data = data
        self.logger.info(
            f"Loaded {len(self.data)} ledger entries from {self.filename}")

    def find(self, *, idempotency_key: str) -> "LedgerEntry[LedgerEvent] | None":
        "Ledgerのイベントを冪等キーから検索する"
        for entry in self.data:
            if entry.event.idempotency_key == idempotency_key:
                return entry
        return None

    async def wait_saved(self, *, ids: list[int]):
        "Ledgerのイベントが保存されるまで待つ"
        while True:
            if all(id in self.wrote for id in ids):
                return
            if self.write_failed:
                self.pos.request_stop()
                cause = next(
                    (self.exception[id] for id in ids if id in self.exception), None)
                raise RuntimeError("Failed to write ledger entry") from cause
            await asyncio.sleep(0.1)


    def get(self, *, id: int) -> "LedgerEntry[LedgerEvent] | None":
        "LedgerのイベントをIDから取得する"
        for event in self.data:
            if event.id == id:
                return event
        return None

    def after(self, *, id: int) -> list["LedgerEntry[LedgerEvent]"]:
        "LedgerのイベントをID以降で取得する"
        return [e for e in self.data if e.id > id]

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
        _cash_count: CashCount = CashCount()
        _last_event: LedgerEntry[LedgerEvent] | None = None
        for entry in reversed(self.data):
            match entry.event:
                case (
                    OpenEvent(cash_count=cash_count)
                    | CloseEvent(cash_count=cash_count)
                    | CashCountEvent(cash_count=cash_count)
                ):
                    _cash_count = cash_count
                    _last_event = entry
                    break

        for entry in self.after(id=_last_event.id if _last_event else 0):
            match entry.event:
                case (
                    SaleEvent(cash_count=cash_count)
                    | VoidEvent(cash_count=cash_count)
                    | RefundEvent(cash_count=cash_count)
                    | CashInEvent(cash_count=cash_count)
                    | CashOutEvent(cash_count=cash_count)
                ):
                    _cash_count += cash_count

        return _cash_count

    def current_boundary(self) -> int:
        "Ledgerのイベントから最後の締めIDを取得する．指定された会計が締め済みかどうかの判定などに使えます"
        for entry in reversed(self.data):
            match entry.event:
                case CloseEvent():
                    return entry.id
        return 0
