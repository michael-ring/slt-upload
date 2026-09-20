from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_redirect_uri: str = "http://localhost:8000/auth/discord/callback"
    discord_guild_ids: str = ""
    discord_api_base_url: str = "https://discord.com/api/v10"
    discord_authorize_url: str = "https://discord.com/oauth2/authorize"
    discord_exchange_url: str = "https://discord.com/api/oauth2/token"

    session_secret: str = ""
    session_max_age_seconds: int = 12 * 60 * 60
    cookie_secure: bool = False

    source_s3_bucket: str = ""
    source_s3_endpoint_url: str | None = None
    source_s3_region: str | None = None
    source_s3_access_key_id: str | None = None
    source_s3_secret_access_key: str | None = None

    upload_path: Path = Path("uploads")

    project_cache_ttl_seconds: int = 15 * 60
    max_upload_size_bytes: int = 25 * 1024 * 1024
    host: str = "127.0.0.1"
    port: int = 8000
    site_ssl_key: str | None = None
    site_ssl_cert: str | None = None

    @property
    def allowed_guild_ids(self) -> tuple[str, ...]:
        """Return configured Discord guild IDs in their configured order."""
        return tuple(guild_id.strip() for guild_id in self.discord_guild_ids.split(",") if guild_id.strip())

    def missing_discord_settings(self) -> tuple[str, ...]:
        """Return the Discord settings required before starting OAuth."""
        missing: list[str] = []
        if not self.discord_client_id:
            missing.append("DISCORD_CLIENT_ID")
        if not self.discord_client_secret:
            missing.append("DISCORD_CLIENT_SECRET")
        if not self.discord_redirect_uri:
            missing.append("DISCORD_REDIRECT_URI")
        if not self.allowed_guild_ids:
            missing.append("DISCORD_GUILD_IDS")
        return tuple(missing)

    def missing_source_s3_settings(self) -> tuple[str, ...]:
        """Return the source S3 settings required for project discovery."""
        missing: list[str] = []
        if not self.source_s3_bucket:
            missing.append("SOURCE_S3_BUCKET")
        return tuple(missing)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache process-wide settings."""
    return Settings()
