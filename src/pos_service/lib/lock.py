import asyncio


class NamedLock(asyncio.Lock):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def __repr__(self):
        return f"<NamedLock name={self.name} locked={self.locked()}>"
