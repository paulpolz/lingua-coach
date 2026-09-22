from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/config.py → backend root is always parents[1] (local or /app in Docker).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "local"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    database_url: str = "postgresql+asyncpg://lingua:lingua@localhost:5432/lingua_coach"
    clerk_secret_key: str = ""
    # Explicit Clerk JWT issuer override (exact match). If unset, any issuer
    # matching the Clerk Development pattern (`https://*.clerk.accounts.dev`)
    # is accepted — see app/core/clerk_auth.py.
    clerk_jwt_issuer: str = ""
    gemini_api_key: str = ""
    gemini_model_chat: str = "gemini-2.0-flash"
    gemini_model_lesson: str = "gemini-2.0-pro"
    gemini_timeout_seconds: int = 120
    cors_origins: str = "http://localhost:3000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    chat_rate_limit_per_hour: int = 60
    lesson_start_rate_limit_per_day: int = 10
    max_message_chars: int = 4000
    chat_context_messages: int = 10
    pace_window_hours: int = 24
    skills_dir: str = str(_BACKEND_ROOT / "skills")
    content_dir: str = str(_BACKEND_ROOT / "content")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
