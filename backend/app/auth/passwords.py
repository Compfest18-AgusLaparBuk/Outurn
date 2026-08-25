from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import OuturnError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def require_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise OuturnError(
            "Password must be between 12 and 256 characters.",
            code="INVALID_PASSWORD",
            status_code=422,
        )
    return hash_password(password)
