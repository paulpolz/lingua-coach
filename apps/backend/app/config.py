from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/config.py → backend root is always parents[1] (local or /app in Docker).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # extra="ignore": .env also holds variables for other libraries (e.g. LANGSMITH_API_KEY
    # for the LangSmith SDK); pydantic-settings would otherwise refuse to start on them.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # A typo (e.g. "prod") fails at startup instead of silently skipping the production checks.
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    metrics_enabled: bool = True
    database_url: str = "postgresql+asyncpg://lingua:lingua@localhost:5432/lingua_coach"
    clerk_secret_key: str = ""
    # Exact Clerk JWT issuer. Required outside `local`; locally an unset value accepts
    # any Clerk Development issuer (`https://*.clerk.accounts.dev`). See core/clerk_auth.py.
    clerk_jwt_issuer: str = ""
    # Only Google (Gemini via langchain-google-genai) is implemented; see services/structured_llm.py.
    llm_provider: Literal["google"] = "google"
    llm_api_key: str = ""
    llm_model_chat: str = "gemini-3.5-flash-lite"
    llm_model_lesson: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: int = 120
    cors_origins: str = "http://localhost:3000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    chat_rate_limit_per_hour: int = 60
    lesson_start_rate_limit_per_day: int = 2
    llm_rpm_limit: int = 15
    llm_input_tpm_limit: int = 250_000
    llm_rpd_limit: int = 500
    max_message_chars: int = 4000
    chat_context_messages: int = 10
    pace_window_hours: int = 24
    # Longest gap between lesson-chat messages that still counts as practice time.
    # A measurement constant, not a lesson length (lessons have no default length).
    lesson_idle_cap_minutes: int = 5
    skills_dir: str = str(_BACKEND_ROOT / "skills")
    # Read from LANGSMITH_TRACING, which the LangSmith SDK also reads. Local and staging
    # trace every LLM call in full; production never does (checked below).
    langsmith_tracing: bool = False
    # The legacy name the LangChain/LangSmith SDKs still honor.
    langchain_tracing_v2: bool = False

    @model_validator(mode="after")
    def _check_deployment_safety(self) -> Settings:
        # Fail at startup: an unset issuer would trust tokens from any Clerk dev instance.
        if self.app_env != "local" and not self.clerk_jwt_issuer:
            raise ValueError(f"CLERK_JWT_ISSUER is required when APP_ENV={self.app_env!r}")
        # Traces hold full prompts and replies; production learner data never goes to LangSmith.
        if self.app_env == "production" and (self.langsmith_tracing or self.langchain_tracing_v2):
            raise ValueError("LANGSMITH_TRACING and LANGCHAIN_TRACING_V2 must be false when APP_ENV='production'")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
