from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'LiveRoll'
    environment: str = 'development'
    secret_key: str = Field(default='dev_secret_key_change_in_production_123', min_length=32)
    token_encryption_key: str = Field(default='dev_token_encryption_key_change_prod_123', min_length=32)

    database_url: str = 'sqlite+aiosqlite:///./dev.db'
    sync_database_url: str = 'sqlite:///./dev.db'
    redis_url: str = 'redis://localhost:6379/0'

    session_cookie_name: str = 'roleta_session'
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    csrf_header_name: str = 'x-csrf-token'

    twitch_client_id: str = ''
    twitch_client_secret: str = ''
    twitch_redirect_uri: str = 'http://localhost:8000/oauth/twitch/callback'

    google_client_id: str = ''
    google_client_secret: str = ''
    google_redirect_uri: str = 'http://localhost:8000/oauth/google/callback'
    google_auth_client_id: str = ''
    google_auth_client_secret: str = ''
    google_auth_redirect_uri: str = 'http://localhost:8000/auth/google/callback'
    github_auth_client_id: str = ''
    github_auth_client_secret: str = ''
    github_auth_redirect_uri: str = 'http://localhost:8000/auth/github/callback'

    cors_origins: str = 'http://localhost:8000'
    overlay_token_ttl_seconds: int = 60 * 60 * 24 * 365

    default_command: str = '!participar'
    youtube_polling_floor_seconds: float = 2.0
    youtube_backoff_cap_seconds: float = 60.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
