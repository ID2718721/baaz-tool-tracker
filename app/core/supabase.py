from functools import lru_cache

from supabase import Client, create_client

from app.core.config import get_settings


@lru_cache
def get_supabase_client() -> Client:
    """Создаёт и кэширует клиент supabase-py."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_key)
