import typing

import pydantic

if typing.TYPE_CHECKING:
    from ..pos import POSService


class AccessTokenResponse(pydantic.BaseModel):
    access_token: str
    expires_in: int
    refresh_token: str
    scope: str
    token_type: str


class UserInfoResponse(pydantic.BaseModel):
    id: str
    username: str


class DiscordAPI:
    "Discord APIを扱う簡易ラッパー"

    API_VERSION: typing.Final[int] = 10
    API_URL: typing.Final[str] = f"https://discord.com/api/v{API_VERSION}"

    def get_api_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.API_URL}{path}"

    def __init__(self, pos: "POSService"):
        self.pos = pos
        self.client_secret: str = self.pos.conf["client_secret"]

    async def get_access_token(self, code: str, redirect_uri: str) -> AccessTokenResponse:
        if self.pos.bot.user is None:
            raise RuntimeError("Bot user is not ready")

        url = self.get_api_url("/oauth2/token")
        data = {
            "client_id": self.pos.bot.user.id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with self.pos.bot.app.session.post(url, data=data, headers=headers) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Failed to get access token: {response.status}")
            return AccessTokenResponse(**await response.json())

    async def get_user_info(self, access_token: str) -> UserInfoResponse:
        url = self.get_api_url("/users/@me")
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self.pos.bot.app.session.get(url, headers=headers) as response:
            return UserInfoResponse(**await response.json())
