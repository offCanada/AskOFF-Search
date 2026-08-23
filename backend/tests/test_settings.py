import pytest
from pydantic import ValidationError

from config.settings import Settings


def test_settings_reject_wildcard_cors_with_credentials_enabled():
    with pytest.raises(ValidationError, match="must not contain"):
        Settings(cors_origins=["*"])


def test_production_settings_require_tls_verification_and_authentication():
    with pytest.raises(ValidationError, match="TLS"):
        Settings(environment="production", cors_origins=["https://search.example.com"])


def test_production_settings_reject_debug_mode():
    with pytest.raises(ValidationError, match="debug"):
        Settings(
            environment="production",
            api_debug=True,
            cors_origins=["https://search.example.com"],
            opensearch_use_ssl=True,
            opensearch_verify_certs=True,
            opensearch_username="service-user",
            opensearch_password="placeholder-only",
        )


def test_production_settings_accept_explicit_secure_configuration():
    settings = Settings(
        environment="production",
        cors_origins=["https://search.example.com"],
        opensearch_use_ssl=True,
        opensearch_verify_certs=True,
        opensearch_username="service-user",
        opensearch_password="placeholder-only",
    )
    assert settings.environment == "production"
