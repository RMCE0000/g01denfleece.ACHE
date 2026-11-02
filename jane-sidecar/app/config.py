"""Environment settings for the sidecar. Chatwoot keeps its own Rails env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SCHEMA = _REPO_ROOT / "sql" / "001_init_g01_schema.sql"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="G01_", env_file=".env", extra="ignore")

    database_url: str = ""
    redis_url: str = "redis://localhost:6379/1"
    allow_memory_store: bool = True
    boot_on_startup: bool = True
    seed_demo: bool = True
    schema_path: str = str(_DEFAULT_SCHEMA)
    public_base_url: str = "http://localhost:8000"
    admin_token: str = ""

    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_deliberation_model: str = "gemini-2.5-pro"
    gemini_embedding_model: str = "text-embedding-004"

    chatwoot_base_url: str = "http://localhost:3000"
    chatwoot_account_id: int = 1
    chatwoot_api_token: str = ""
    chatwoot_platform_token: str = ""
    chatwoot_inbox_id: int = 1
    chatwoot_webhook_secret: str = ""
    jane_user_id: int = 1

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_sponsor_price_id: str = ""
    stripe_success_url: str = "http://localhost:8000/ui/hud?checkout=success"
    stripe_cancel_url: str = "http://localhost:8000/ui/hud?checkout=cancel"

    poll_mature_hours: int = 24
    match_similarity_threshold: float = 0.72
    full_manual_hours_per_week: float = 40.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
