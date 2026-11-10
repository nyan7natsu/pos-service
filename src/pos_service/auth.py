import asyncio
import os
import secrets
import typing

import aiofiles


class Authenticator:

    def __init__(self):
        self.__password: str = ""

    async def load_password_file(self, filename: str = "password"):
        "パスワードファイルを読み込みます。"
        try:
            async with aiofiles.open(filename, "r", encoding="utf-8") as f:
                self.__password = (await f.read()).strip()
            os.chmod(filename, 0o600)
        except FileNotFoundError:
            self.regen_password()
            await self.write_password_file(filename)

    async def write_password_file(self, filename: str = "password"):
        "パスワードファイルを書き込みます。"
        async with aiofiles.open(filename, "w", encoding="utf-8") as f:
            await f.write(self.__password)
        os.chmod(filename, 0o600)

    def check_password(self, password: str) -> bool:
        "パスワードが正しいかどうかを確認します。"
        if not self.__password:
            return False
        return secrets.compare_digest(
            self.__password.encode(), password.encode(errors="replace")
        )

    def regen_password(self) -> str:
        self.__password = secrets.token_urlsafe(32)
        return self.__password

    def get_password(self) -> str:
        return self.__password

    def mask_password(self, data: typing.Any) -> str:
        "パスワードをマスクします。"
        return str(data).replace(self.__password, "********")
