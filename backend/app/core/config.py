"""Runtime configuration.

Secrets come from the environment or a local .env file. Production deployments
should inject values from AWS Secrets Manager into the task environment.
"""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    demo_mode: bool = True
    project_name: str = "PMAB Remittance Intelligence"

    database_url: str = "sqlite:///" + (ROOT / "data" / "pmab.db").as_posix()
    redis_url: str = "redis://localhost:6379/0"
    use_celery: bool = False
    auto_create_schema: bool = True

    jwt_secret: str = "local-dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 480
    hash_iterations: int = 200_000

    demo_admin_password: str = "ChangeMe-Demo-Only"
    demo_analyst_password: str = "ChangeMe-Demo-Only"
    demo_viewer_password: str = "ChangeMe-Demo-Only"

    storage_backend: str = "local"
    local_storage_path: str = str(ROOT / "data" / "edi")
    s3_bucket: str | None = None
    s3_prefix: str = "edi/835"
    s3_kms_key_id: str | None = None
    aws_region: str = "us-east-1"

    llm_provider: str = "mock"
    bedrock_model_id: str = ""
    bedrock_phi_approved: bool = False
    bedrock_timeout_seconds: int = 30
    bedrock_max_retries: int = 2
    embedding_provider: str = "local_hash"
    embedding_dimensions: int = 256

    central_reach_api_enabled: bool = False
    sftp_enabled: bool = False
    sftp_host: str = ""
    sftp_port: int = 22
    sftp_username: str = ""
    sftp_remote_dir: str = ""
    sftp_private_key_path: str = ""

    reconciliation_tolerance: Decimal = Decimal("0.00")
    denial_rate_alert_threshold: Decimal = Decimal("0.25")
    payment_delay_threshold_days: int = 30
    underpayment_tolerance: Decimal = Decimal("0.01")
    anomaly_min_periods: int = 4
    anomaly_min_claims: int = 5
    anomaly_z_threshold: float = 3.5
    anomaly_pct_change_threshold: float = 0.50
    isolation_forest_min_observations: int = 50
    human_review_exposure_threshold: Decimal = Decimal("1000.00")
    agent_max_iterations: int = 8
    agent_timeout_seconds: int = 20

    stored_filename_pattern: str = "PLUTUS_{date}_{original}_{hash}.edi"
    ingest_root: str = str(ROOT / "sample_data")
    max_upload_bytes: int = 5_000_000
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    count_partial_denials: bool = True
    exclude_reversals_from_denial_rate: bool = True

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("llm_provider", "storage_backend", "embedding_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def uses_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


def validate_runtime(settings: Settings) -> None:
    """Fail closed for unsafe production combinations."""
    if settings.environment != "production":
        return
    problems: list[str] = []
    if settings.demo_mode:
        problems.append("DEMO_MODE must be false in production")
    if settings.jwt_secret in {"", "local-dev-only-change-me"}:
        problems.append("JWT_SECRET must be set from Secrets Manager in production")
    if settings.database_url.startswith("sqlite"):
        problems.append("production requires PostgreSQL")
    if settings.storage_backend == "local":
        problems.append("production storage backend must be s3")
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
