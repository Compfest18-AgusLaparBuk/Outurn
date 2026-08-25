from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.errors import GateGuardError


def _fernet(settings: Settings) -> Fernet:
    key_material = settings.webhook_secret_key or settings.app_api_key
    if not key_material:
        if settings.app_env.casefold() == "production":
            raise GateGuardError(
                "Webhook secret storage is not configured.",
                code="WEBHOOK_SECRET_STORAGE_UNAVAILABLE",
                status_code=503,
            )
        key_material = "GateGuard local webhook secret store; never use in production"
    derived = base64.urlsafe_b64encode(hashlib.sha256(key_material.encode()).digest())
    return Fernet(derived)


def encrypt_secret(value: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str, settings: Settings) -> str:
    try:
        return _fernet(settings).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise GateGuardError(
            "Webhook signing secret cannot be decrypted safely.",
            code="WEBHOOK_SECRET_UNAVAILABLE",
            status_code=503,
        ) from exc
