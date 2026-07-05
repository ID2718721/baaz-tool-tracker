from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Настройки приложения TMS, загружаемые из переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Локальный .env важнее системных переменных (часто остаётся example.supabase.co).
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    supabase_url: str
    supabase_key: str

    app_name: str = "BAAZ TMS"
    app_version: str = "0.1.0"
    debug: bool = False

    cors_origins: list[str] = ["*"]

    tms_integration_secret: str = ""

    jwt_secret_key: str = "change-me-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480
    access_token_cookie_name: str = "tms_access_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"


@lru_cache
def get_settings() -> Settings:
    return Settings()
