"""Configuration management for Stock App."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class SnowflakeSettings:
    """Snowflake connection settings."""
    account: str = ""
    jwt_account_identifier: str = ""
    connector_account_identifier: str = ""
    user: str = ""
    warehouse: str = ""
    database: str = "Sodatone"
    schema: str = "Sodatone"
    role: str = ""
    private_key_path_env_var: str = "SNOWFLAKE_PRIVATE_KEY_PATH"


@dataclass
class SpotifySettings:
    """Spotify API settings."""
    client_id_env_var: str = "SPOTIFY_CLIENT_ID"
    client_secret_env_var: str = "SPOTIFY_CLIENT_SECRET"
    token_url: str = "https://accounts.spotify.com/api/token"
    api_base_url: str = "https://api.spotify.com/v1"

    @property
    def client_id(self) -> Optional[str]:
        return os.environ.get(self.client_id_env_var)

    @property
    def client_secret(self) -> Optional[str]:
        return os.environ.get(self.client_secret_env_var)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


@dataclass
class ChartexSettings:
    """Chartex API settings for TikTok data."""
    app_id_env_var: str = "CHARTEX_APP_ID"
    app_token_env_var: str = "CHARTEX_APP_TOKEN"
    api_base_url: str = "https://api.chartex.com/external/v1"

    @property
    def app_id(self) -> Optional[str]:
        return os.environ.get(self.app_id_env_var)

    @property
    def app_token(self) -> Optional[str]:
        return os.environ.get(self.app_token_env_var)

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_token)


@dataclass
class Settings:
    """Application settings."""
    snowflake: SnowflakeSettings = field(default_factory=SnowflakeSettings)
    spotify: SpotifySettings = field(default_factory=SpotifySettings)
    chartex: ChartexSettings = field(default_factory=ChartexSettings)


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """Load settings from YAML configuration file."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "settings.yaml"

    if not config_path.exists():
        return Settings()

    with config_path.open() as f:
        data = yaml.safe_load(f) or {}

    snowflake_data = data.get("snowflake", {})
    spotify_data = data.get("spotify", {})
    chartex_data = data.get("chartex", {})

    return Settings(
        snowflake=SnowflakeSettings(**snowflake_data),
        spotify=SpotifySettings(**spotify_data),
        chartex=ChartexSettings(**chartex_data),
    )


# Global settings instance
settings = load_settings()
