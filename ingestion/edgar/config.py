"""Settings for the ingestion job, read from environment variables / ingestion/.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    user_agent: str
    form_types: tuple[str, ...]
    lookback_days: int
    # The SEC allows 10 requests/second; stay a little under it.
    requests_per_second: float = 8.0

    @property
    def cutoff(self) -> date:
        """Oldest filing date to keep."""
        return date.today() - timedelta(days=self.lookback_days)


@dataclass(frozen=True)
class GcpSettings:
    project_id: str
    bucket: str
    location: str  # Vertex AI Search location: "global", "us" or "eu"
    data_store_id: str
    engine_id: str

    @property
    def collection(self) -> str:
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            "/collections/default_collection"
        )

    @property
    def data_store(self) -> str:
        return f"{self.collection}/dataStores/{self.data_store_id}"

    @property
    def serving_config(self) -> str:
        return f"{self.collection}/engines/{self.engine_id}/servingConfigs/default_search"


def load_gcp_settings() -> GcpSettings:
    load_dotenv()
    project = os.getenv("GCP_PROJECT_ID", "").strip()
    bucket = os.getenv("GCS_BUCKET", "").strip()
    if not project or project.startswith("your-") or not bucket or bucket.startswith("your-"):
        raise SystemExit("Set GCP_PROJECT_ID and GCS_BUCKET in ingestion/.env first.")
    return GcpSettings(
        project_id=project,
        bucket=bucket,
        location=os.getenv("GCP_LOCATION", "global"),
        data_store_id=os.getenv("VERTEX_SEARCH_DATA_STORE_ID", "sec-filings"),
        engine_id=os.getenv("VERTEX_SEARCH_ENGINE_ID", "sec-filings-search"),
    )


def load_settings() -> Settings:
    load_dotenv()
    user_agent = os.getenv("SEC_USER_AGENT", "").strip().strip('"')
    if "@" not in user_agent or "example.com" in user_agent:
        raise SystemExit(
            "Set SEC_USER_AGENT in ingestion/.env to your real name and email, "
            'for example SEC_USER_AGENT="Jane Doe jane@gmail.com". '
            "The SEC blocks automated requests without it."
        )
    forms = tuple(
        f.strip().upper()
        for f in os.getenv("FORM_TYPES", "10-K,10-Q,8-K").split(",")
        if f.strip()
    )
    return Settings(
        user_agent=user_agent,
        form_types=forms,
        lookback_days=int(os.getenv("LOOKBACK_DAYS", "730")),
    )
