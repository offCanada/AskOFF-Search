from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASKOFF_", env_file=".env")

    opensearch_hosts: list[str] = ["localhost:9200"]
    opensearch_index: str = "askoff_products"
    opensearch_use_ssl: bool = False
    opensearch_username: Optional[str] = None
    opensearch_password: Optional[str] = None
    opensearch_verify_certs: bool = False
    opensearch_timeout_seconds: float = 5.0
    opensearch_max_retries: int = 2
    opensearch_pool_maxsize: int = 20

    raw_data_path: Path = (
        Path("data/raw/off_canada_with_images.parquet")
        if Path("data/raw/off_canada_with_images.parquet").exists()
        else Path("data/raw/normalized.parquet")
    )
    processed_dir: Path = Path("data/processed")
    dataset_url: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    request_max_query_length: int = 500
    request_max_page_size: int = 100
    request_max_offset: int = 10_000
    request_max_compare_ids: int = 50
    logging_level: str = "INFO"
    environment: str = "development"

    pipeline_batch_size: int = 1000

    # Development defaults. Production deployments must provide their explicit
    # trusted origins through ASKOFF_CORS_ORIGINS.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    completeness_weight: float = 0.15

    @model_validator(mode="after")
    def validate_deployment_settings(self) -> "Settings":
        if "*" in self.cors_origins:
            raise ValueError(
                "ASKOFF_CORS_ORIGINS must not contain '*' when credentials are enabled"
            )
        if bool(self.opensearch_username) != bool(self.opensearch_password):
            raise ValueError("OpenSearch username and password must be configured together")
        if self.environment.lower() == "production":
            if self.api_debug:
                raise ValueError("production requires API debug mode to be disabled")
            if not self.opensearch_use_ssl or not self.opensearch_verify_certs:
                raise ValueError("production requires OpenSearch TLS and certificate verification")
            if not self.opensearch_username or not self.opensearch_password:
                raise ValueError("production requires OpenSearch authentication")
            if not self.cors_origins:
                raise ValueError("production requires explicit CORS origins")
        return self


settings = Settings()
