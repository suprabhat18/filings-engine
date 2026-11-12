"""Backend settings, read from environment variables (or backend/.env locally)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

FORM_TYPES = ("10-K", "10-Q", "8-K")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str = ""
    gcp_location: str = "global"  # Vertex AI Search location
    vertex_search_engine_id: str = "sec-passages-search"
    results_per_query: int = 8

    gemini_model: str = "gemini-3.8-flash"
    gemini_location: str = "global"

    google_oauth_client_id: str = ""
    # Optional: comma-separated emails allowed to sign in. Empty = any Google account.
    allowed_emails: str = ""

    # Cost and abuse protection
    rate_limit_per_minute: int = 10      # searches per user per minute
    daily_user_quota: int = 50           # searches per user per day
    daily_global_quota: int = 1000       # searches across all users per day

    cors_origins: str = "http://localhost:3000"

    @property
    def serving_config(self) -> str:
        return (
            f"projects/{self.gcp_project_id}/locations/{self.gcp_location}"
            f"/collections/default_collection/engines/{self.vertex_search_engine_id}"
            "/servingConfigs/default_search"
        )

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
