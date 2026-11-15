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
    avatar: str | None
    discriminator: str
    public_flags: int
    flags: int
    email: str | None
    verified: bool
    locale: str
    mfa_enabled: bool


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
        self.client_id: int = self.pos.bot.app.conf["client_id"]
        self.client_secret: str = self.pos.bot.app.conf["client_secret"]

    async def get_access_token(self, code: str, redirect_uri: str) -> AccessTokenResponse:
        url = self.get_api_url("/oauth2/token")
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with self.pos.bot.app.session.post(url, data=data, headers=headers) as response:
            return AccessTokenResponse(**await response.json())

    async def get_user_info(self, access_token: str) -> UserInfoResponse:
        url = self.get_api_url("/users/@me")
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self.pos.bot.app.session.get(url, headers=headers) as response:
            return UserInfoResponse(**await response.json())
