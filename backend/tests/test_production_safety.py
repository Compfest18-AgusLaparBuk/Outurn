import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_config_fails_closed_without_real_database_and_secrets():
    with pytest.raises(ValidationError):
        Settings(app_env="production")


def test_production_config_accepts_distinct_secrets_and_postgres():
    settings = Settings(
        app_env="production",
        app_public_origin="https://gateguard.example.com",
        database_url="postgresql+psycopg://gateguard:secret@db/gateguard",
        cors_origins=["https://gateguard.example.com"],
        app_api_key="a" * 32,
        webhook_secret_key="w" * 32,
        cookie_secure=True,
    )
    assert settings.app_env == "production"


@pytest.mark.parametrize("origin", ["*", "https://*.example.com", "https://user:pass@example.com"])
def test_cors_rejects_wildcards_and_credentials(origin):
    with pytest.raises(ValidationError):
        Settings(cors_origins=[origin], app_public_origin=origin)
