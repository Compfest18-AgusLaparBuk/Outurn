from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="forbid",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_public_origin: str = "http://localhost:3000"
    database_url: str = "sqlite:///./gateguard.db"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    max_upload_bytes: int = 10 * 1024 * 1024
    document_storage_root: str = "./uploads"
    document_allowed_mime_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["application/pdf", "image/jpeg", "image/png"]
    )
    max_pdf_pages: int = 50
    max_pdf_text_chars: int = 500_000
    max_image_pixels: int = 40_000_000
    rate_limit_requests: int = 180
    rate_limit_window_seconds: int = 60
    app_api_key: str | None = None
    # Accepted only so the shared root .env can be parsed; this legacy escape
    # hatch is deliberately rejected below and is never used for auth.
    supervisor_override_key: str | None = None
    webhook_secret_key: str | None = None
    backend_api_url: str | None = None
    backend_api_key: str | None = None
    backend_timeout_ms: int | None = None
    postgres_password: str | None = None
    seed_user_1_email: str | None = None
    seed_user_1_password: str | None = None
    seed_user_1_display_name: str | None = None
    seed_user_1_role: str | None = None
    seed_user_2_email: str | None = None
    seed_user_2_password: str | None = None
    seed_user_2_display_name: str | None = None
    seed_user_2_role: str | None = None
    session_ttl_seconds: int = 8 * 60 * 60
    cookie_secure: bool | None = None
    app_version: str = "0.1.0"

    extraction_provider: Literal["auto", "local", "openai", "openrouter", "paddle"] = "auto"
    critical_confidence_threshold: float = 0.75
    max_ai_concurrency: int = 4
    worker_poll_interval_seconds: float = 2.0
    worker_heartbeat_interval_seconds: float = 10.0

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 45.0
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 45.0
    paddle_device: str = "cpu"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("document_allowed_mime_types", mode="before")
    @classmethod
    def parse_document_mime_types(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value

    @field_validator("app_public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("APP_PUBLIC_ORIGIN must be an absolute HTTP(S) origin")
        if parsed.username or parsed.password or "*" in parsed.netloc:
            raise ValueError("APP_PUBLIC_ORIGIN must not contain credentials or wildcards")
        if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("APP_PUBLIC_ORIGIN must not include a path, query, or fragment")
        return value.strip().rstrip("/")

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in value:
            parsed = urlparse(raw.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("CORS_ORIGINS must contain absolute HTTP(S) origins")
            if "*" in parsed.netloc or "*" in parsed.path or parsed.username or parsed.password:
                raise ValueError("CORS_ORIGINS must not contain wildcards or credentials")
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                raise ValueError("CORS_ORIGINS entries must not include paths or queries")
            normalized.append(raw.strip().rstrip("/"))
        if not normalized:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        return list(dict.fromkeys(normalized))

    @field_validator("critical_confidence_threshold")
    @classmethod
    def validate_threshold(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("CRITICAL_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return value

    @field_validator(
        "max_upload_bytes",
        "max_pdf_pages",
        "max_pdf_text_chars",
        "max_image_pixels",
        "rate_limit_requests",
        "rate_limit_window_seconds",
        "max_ai_concurrency",
        "session_ttl_seconds",
    )
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Resource-limit settings must be positive integers")
        return value

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.supervisor_override_key:
            raise ValueError(
                "SUPERVISOR_OVERRIDE_KEY is unsupported; use an authenticated supervisor session"
            )
        if self.app_public_origin not in self.cors_origins:
            raise ValueError("APP_PUBLIC_ORIGIN must be included in CORS_ORIGINS")
        if self.app_env.casefold() != "production":
            return self

        if not self.app_api_key or len(self.app_api_key) < 32:
            raise ValueError("APP_API_KEY must be set to at least 32 characters in production")
        if any(origin == "*" for origin in self.cors_origins):
            raise ValueError("Wildcard CORS origins are forbidden in production")
        if self.cookie_secure is not True:
            raise ValueError("COOKIE_SECURE=true is required in production")
        if self.database_url.startswith("sqlite"):
            raise ValueError(
                "SQLite is supported only for local development. "
                "Configure PostgreSQL for APP_ENV=production"
            )
        if not self.webhook_secret_key or len(self.webhook_secret_key) < 32:
            raise ValueError(
                "WEBHOOK_SECRET_KEY must be set to at least 32 characters in production"
            )
        if self.openai_api_key and urlparse(self.openai_base_url).scheme != "https":
            raise ValueError("OPENAI_BASE_URL must use HTTPS in production")
        if self.openrouter_api_key and urlparse(self.openrouter_base_url).scheme != "https":
            raise ValueError("OPENROUTER_BASE_URL must use HTTPS in production")
        return self

    @property
    def secure_cookies(self) -> bool:
        return (
            self.cookie_secure
            if self.cookie_secure is not None
            else self.app_env.casefold() == "production"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
