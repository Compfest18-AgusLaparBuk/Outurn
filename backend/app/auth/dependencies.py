from __future__ import annotations

from functools import lru_cache

from app.repositories.reconciliations import UserRow

SYSTEM_USER_EMAIL = "operator@outurn.local"


@lru_cache(maxsize=1)
def system_user() -> UserRow:
    """Provision and return the shared operator principal (authentication is disabled)."""
    from app.api.operations import get_operations

    return get_operations().ensure_system_user(SYSTEM_USER_EMAIL)


def current_user() -> UserRow:
    """Every request shares the workspace operator; no login is required."""
    return system_user()


def optional_current_user() -> UserRow:
    return system_user()


def require_role(*_roles: str):
    """Kept for call-site compatibility; role checks are bypassed without authentication."""

    def dependency() -> UserRow:
        return current_user()

    return dependency
