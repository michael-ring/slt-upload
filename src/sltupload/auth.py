from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from sltupload.config import Settings


class DiscordAuthError(Exception):
    """Raised when Discord cannot authenticate or authorize a user."""


@dataclass(frozen=True, slots=True)
class DiscordUser:
    """The small Discord user record needed by the application."""

    discord_id: str
    username: str


class DiscordOAuth:
    """Exchange Discord OAuth codes and verify guild membership."""

    scopes = ("identify", "guilds.members.read")

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authorization_url(self, state: str) -> str:
        """Build the Discord authorization URL for one login attempt."""
        params = {
            "response_type": "code",
            "client_id": self.settings.discord_client_id,
            "scope": " ".join(self.scopes),
            "state": state,
            "redirect_uri": self.settings.discord_redirect_uri,
        }
        return f"{self.settings.discord_authorize_url}?{urlencode(query=params)}"

    async def authenticate(self, code: str) -> DiscordUser:
        """Exchange a code, identify its user, and check configured guilds."""
        missing = self.settings.missing_discord_settings()
        if missing:
            raise DiscordAuthError("Discord OAuth is not configured.")

        timeout = httpx.Timeout(timeout=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                access_token = await self._exchange_code(client=client, code=code)
                user = await self._get_user(client=client, access_token=access_token)
                await self._check_membership(client=client, access_token=access_token)
        except DiscordAuthError:
            raise
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise DiscordAuthError("Discord login is unavailable.") from exc
        return user

    async def _exchange_code(self, client: httpx.AsyncClient, code: str) -> str:
        response = await client.post(
            url=self.settings.discord_exchange_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.discord_redirect_uri,
            },
            auth=(self.settings.discord_client_id, self.settings.discord_client_secret),
        )
        if response.is_error:
            raise DiscordAuthError("Discord rejected the OAuth code.")

        payload = response.json()
        if not isinstance(payload, dict):
            raise DiscordAuthError("Discord returned an invalid token response.")
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise DiscordAuthError("Discord did not return an access token.")
        return access_token

    async def _get_user(self, client: httpx.AsyncClient, access_token: str) -> DiscordUser:
        response = await client.get(
            url=f"{self.settings.discord_api_base_url}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.is_error:
            raise DiscordAuthError("Discord did not return the current user.")

        payload = response.json()
        if not isinstance(payload, dict):
            raise DiscordAuthError("Discord returned an invalid user profile.")
        discord_id = payload.get("id")
        username = payload.get("username")
        if not isinstance(discord_id, str) or not isinstance(username, str) or not username:
            raise DiscordAuthError("Discord returned an incomplete user profile.")
        return DiscordUser(discord_id=discord_id, username=username)

    async def _check_membership(self, client: httpx.AsyncClient, access_token: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        for guild_id in self.settings.allowed_guild_ids:
            response = await client.get(
                url=f"{self.settings.discord_api_base_url}/users/@me/guilds/{guild_id}/member",
                headers=headers,
            )
            if response.status_code == 200:
                return
            if response.status_code == 404:
                continue
            raise DiscordAuthError("Discord could not verify server membership.")

        raise DiscordAuthError("The Discord account is not connected to an allowed server.")
