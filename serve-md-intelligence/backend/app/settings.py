from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden with a SERVEMD_* environment variable."""

    model_config = SettingsConfigDict(env_prefix="SERVEMD_", env_file=REPO_ROOT / ".env", extra="ignore")

    config_dir: Path = REPO_ROOT / "config"
    data_dir: Path = REPO_ROOT / "data"
    warehouse_path: Path = REPO_ROOT / "data" / "warehouse" / "servemd.duckdb"
    read_only_warehouse: bool = False

    # Shared-secret gate for private deployments. Empty = no auth (local development).
    access_token: str = ""
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def metrics_file(self) -> Path:
        return self.config_dir / "metrics.yaml"

    @property
    def scoring_default_file(self) -> Path:
        return self.config_dir / "scoring_default.yaml"

    @property
    def financial_default_file(self) -> Path:
        return self.config_dir / "financial_default.yaml"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def fixtures_dir(self) -> Path:
        return self.data_dir / "fixtures"

    @property
    def geo_dir(self) -> Path:
        return self.data_dir / "geo"


settings = Settings()
