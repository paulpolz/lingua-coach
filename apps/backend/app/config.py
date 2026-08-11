from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/config.py -> apps/backend -> apps -> repo root.
# In Docker dev the backend is mounted at /app, so parents[3] does not exist;
# skills are mounted at /skills (parents[2] == / -> /skills).
_config_path = Path(__file__).resolve()
try:
    _REPO_ROOT = _config_path.parents[3]
except IndexError:
    _REPO_ROOT = _config_path.parents[2]
_DEFAULT_SKILLS_DIR = str(_REPO_ROOT / "skills")


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
    # Resolves to the repo-root `skills/` dir by default (coordination rule
    # #5 in the plan) regardless of the process's working directory; override
    # via env for non-standard layouts.
    skills_dir: str = _DEFAULT_SKILLS_DIR

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
