import secrets

import typing

class Authenticator:
    def __init__(self):
        self.__password = secrets.token_urlsafe(32)

    def check_password(self, password: str) -> bool:
        "パスワードが正しいかどうかを確認します。"
        return secrets.compare_digest(self.__password.encode(), password.encode())

    def regen_password(self):
        self.__password = secrets.token_urlsafe(32)
        return self.__password

    def get_password(self) -> str:
        return self.__password

    def mask_password(self, data: typing.Any) -> str:
        "パスワードをマスクします。"
        return str(data).replace(self.__password, "********")
