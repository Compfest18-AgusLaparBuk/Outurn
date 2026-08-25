from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.auth.principals import ServicePrincipal
from app.core.config import get_settings
from app.core.errors import GateGuardError, NotFoundError
from app.domain.jobs import ProcessingJobType
from app.domain.models import ShipmentStatus, UserRole
from app.repositories.reconciliations import (
    AuditEventRow,
    Base,
    ReleaseDecisionRow,
    ReviewTaskRow,
    ShipmentCaseRow,
    TrustedShipmentReferenceRow,
    UserRow,
)
from app.services.assurance import calculate_risk, policy_risk_config
from app.services.release_integrity import build_release_snapshot, snapshot_hash
from app.services.secret_store import decrypt_secret, encrypt_secret


def now_utc() -> datetime:
    return datetime.now(UTC)


def validate_webhook_endpoint(endpoint: str, *, production: bool) -> str:
    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise GateGuardError(
            "Webhook endpoints must use a valid HTTPS URL.",
            code="INVALID_WEBHOOK_ENDPOINT",
            status_code=422,
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GateGuardError(
            "Webhook endpoints cannot contain credentials, query strings, or fragments.",
            code="INVALID_WEBHOOK_ENDPOINT",
            status_code=422,
        )
    host = parsed.hostname.casefold().rstrip(".")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if production and parsed.scheme != "https":
        raise GateGuardError(
            "Webhook endpoints must use HTTPS in production.",
            code="INVALID_WEBHOOK_ENDPOINT",
            status_code=422,
        )
    if host in local_hosts and production:
        raise GateGuardError(
            "Local webhook endpoints are not allowed in production.",
            code="INVALID_WEBHOOK_ENDPOINT",
            status_code=422,
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if (
        address
        and (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        )
        and (production or host not in local_hosts)
    ):
        raise GateGuardError(
            "Private or reserved webhook addresses are not allowed.",
            code="INVALID_WEBHOOK_ENDPOINT",
            status_code=422,
        )
    return endpoint.strip()


def validate_connection_base_url(endpoint: str, *, production: bool) -> str:
    """Validate provider base URLs before a future adapter can make requests."""
    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise GateGuardError(
            "Connection base URLs must use a valid HTTP(S) URL.",
            code="INVALID_CONNECTION_URL",
            status_code=422,
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GateGuardError(
            "Connection base URLs cannot contain credentials, query strings, or fragments.",
            code="INVALID_CONNECTION_URL",
            status_code=422,
        )
    host = parsed.hostname.casefold().rstrip(".")
    if production and parsed.scheme != "https":
        raise GateGuardError(
            "Connection base URLs must use HTTPS in production.",
            code="INVALID_CONNECTION_URL",
            status_code=422,
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise GateGuardError(
            "Private or reserved connection addresses are not allowed.",
            code="INVALID_CONNECTION_URL",
            status_code=422,
        )
    return endpoint.strip().rstrip("/")


_SAFE_CONNECTION_KEYS = frozenset(
    {"base_url", "dataset", "region", "tenant", "environment", "timeout_seconds", "mode"}
)
_SECRET_KEY_MARKERS = frozenset(
    {
        "secret",
        "token",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "private_key",
        "credential",
        "authorization",
    }
)
_WEBHOOK_EVENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_SERVICE_SCOPES = frozenset({"shipment.read", "shipment.write"})
_DEFAULT_REVIEW_POLICY = {
    "low_sla_hours": 24,
    "medium_sla_hours": 8,
    "high_sla_hours": 4,
    "critical_sla_hours": 1,
    "require_decision_reason": True,
    "require_high_risk_approval": True,
    "require_critical_exception_approval": True,
}
_DEFAULT_RETENTION_POLICY = {
    "audit_days": 365,
    "document_days": 365,
    "job_days": 90,
    "webhook_days": 90,
}


def normalize_webhook_events(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GateGuardError(
            "Webhook events must be a list.", code="VALIDATION_ERROR", status_code=422
        )
    events = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if len(events) > 20 or any(not _WEBHOOK_EVENT_PATTERN.fullmatch(item) for item in events):
        raise GateGuardError(
            "Webhook events must use short names such as shipment.updated.",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    return events


def normalize_service_scopes(value: object) -> list[str]:
    if not isinstance(value, list):
        raise GateGuardError(
            "Service token scopes must be a list.", code="VALIDATION_ERROR", status_code=422
        )
    scopes = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if not scopes or any(scope not in _SERVICE_SCOPES for scope in scopes):
        raise GateGuardError(
            "The requested service token scope is not allowed.",
            code="INVALID_SERVICE_SCOPE",
            status_code=422,
        )
    return scopes


def normalize_service_expiry(value: object, *, now: datetime | None = None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise GateGuardError(
            "Token expiry must be a timestamp.", code="VALIDATION_ERROR", status_code=422
        )
    current = now or now_utc()
    expiry = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if expiry <= current:
        raise GateGuardError(
            "Token expiry must be in the future.", code="VALIDATION_ERROR", status_code=422
        )
    return expiry


def normalize_review_policy(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateGuardError(
            "Review policy must be an object.", code="VALIDATION_ERROR", status_code=422
        )
    normalized = dict(_DEFAULT_REVIEW_POLICY)
    for key in normalized:
        if key not in value:
            continue
        current = value[key]
        if key.endswith("_hours"):
            try:
                current = int(current)
            except (TypeError, ValueError) as exc:
                raise GateGuardError(
                    "Review SLA values must be whole hours.",
                    code="VALIDATION_ERROR",
                    status_code=422,
                ) from exc
            if not 1 <= current <= 720:
                raise GateGuardError(
                    "Review SLA values must be between 1 and 720 hours.",
                    code="VALIDATION_ERROR",
                    status_code=422,
                )
        elif not isinstance(current, bool):
            raise GateGuardError(
                "Review policy switches must be boolean.",
                code="VALIDATION_ERROR",
                status_code=422,
            )
        normalized[key] = current
    return normalized


def normalize_retention_policy(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise GateGuardError(
            "Retention policy must be an object.", code="VALIDATION_ERROR", status_code=422
        )
    normalized: dict[str, int] = {}
    for key, minimum in (
        ("audit_days", 30),
        ("document_days", 30),
        ("job_days", 7),
        ("webhook_days", 7),
    ):
        raw = value.get(key, _DEFAULT_RETENTION_POLICY[key])
        try:
            days = int(raw)
        except (TypeError, ValueError) as exc:
            raise GateGuardError(
                "Retention windows must be whole days.", code="VALIDATION_ERROR", status_code=422
            ) from exc
        if not minimum <= days <= 3_650:
            raise GateGuardError(
                f"{key} must be between {minimum} and 3650 days.",
                code="VALIDATION_ERROR",
                status_code=422,
            )
        normalized[key] = days
    return normalized


def sanitize_connection_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    """Keep only non-sensitive connection metadata; credentials use a reference."""
    safe: dict[str, Any] = {}
    for raw_key, value in configuration.items():
        key = str(raw_key).strip().casefold()
        if any(marker in key for marker in _SECRET_KEY_MARKERS):
            raise GateGuardError(
                "Credentials must be stored through a server-side credential reference.",
                code="CREDENTIAL_VALUE_REJECTED",
                status_code=422,
            )
        if key not in _SAFE_CONNECTION_KEYS:
            raise GateGuardError(
                "Unsupported connection metadata field.",
                code="UNSUPPORTED_CONNECTION_FIELD",
                status_code=422,
            )
        if isinstance(value, (str, int, float, bool)) or value is None:
            if key == "base_url" and value:
                value = validate_connection_base_url(
                    str(value), production=get_settings().app_env.casefold() == "production"
                )
            safe[key] = value
        else:
            raise GateGuardError(
                "Connection metadata must be a scalar value.",
                code="INVALID_CONNECTION_METADATA",
                status_code=422,
            )
    return safe


class OrganizationRow(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    default_timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    default_locale: Mapped[str] = mapped_column(String(16), default="en-GB")
    default_currency: Mapped[str] = mapped_column(String(8), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FacilityRow(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    code: Mapped[str] = mapped_column(String(40))
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceMembershipRow(Base):
    __tablename__ = "workspace_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(24))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecentObjectRow(Base):
    __tablename__ = "recent_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    object_type: Mapped[str] = mapped_column(String(40), index=True)
    object_id: Mapped[str] = mapped_column(String(36), index=True)
    label: Mapped[str] = mapped_column(String(240))
    href: Mapped[str] = mapped_column(String(320))
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TradePartyRow(Base):
    __tablename__ = "trade_parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    legal_name: Mapped[str] = mapped_column(String(200), index=True)
    trade_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tax_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShipmentPartyRow(Base):
    __tablename__ = "shipment_parties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    party_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_parties.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PartyIdentifierRow(Base):
    __tablename__ = "party_identifiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    party_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_parties.id", ondelete="CASCADE"), index=True
    )
    identifier_type: Mapped[str] = mapped_column(String(40))
    identifier_value: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShipmentItemRow(Base):
    __tablename__ = "shipment_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    line_number: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(400))
    quantity: Mapped[float] = mapped_column(Float, default=0)
    unit_of_measure: Mapped[str] = mapped_column(String(24), default="unit")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    line_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(2), nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gross_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    dangerous_goods: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    un_number: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proper_shipping_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    hazard_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    packing_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    special_handling: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransportLegRow(Base):
    __tablename__ = "transport_legs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(24))
    carrier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(160), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(160), nullable=True)
    planned_departure: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_departure: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vessel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    voyage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    flight: Mapped[str | None] = mapped_column(String(80), nullable=True)
    vehicle_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransportEquipmentRow(Base):
    __tablename__ = "transport_equipment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    equipment_type: Mapped[str] = mapped_column(String(24))
    equipment_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seal_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShipmentDocumentRow(Base):
    __tablename__ = "shipment_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(48), index=True)
    document_reference: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    requirement_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(240))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    storage_key: Mapped[str] = mapped_column(String(320))
    extraction_status: Mapped[str] = mapped_column(String(24), index=True)
    extraction_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DocumentRequirementRow(Base):
    __tablename__ = "document_requirements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    rule_pack_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule_pack_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    document_type: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24))
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    reason: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequirementEvaluationRow(Base):
    __tablename__ = "requirement_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_requirements.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    rule_pack_version: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AssuranceCheckRow(Base):
    __tablename__ = "assurance_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    check_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    summary: Mapped[str] = mapped_column(String(240))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(120))
    source_version: Mapped[str] = mapped_column(String(40), default="1")
    rule_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rule_pack_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ShipmentExceptionRow(Base):
    __tablename__ = "shipment_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    assurance_check_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assurance_checks.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    resolution_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExceptionCommentRow(Base):
    __tablename__ = "exception_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    exception_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_exceptions.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DecisionApprovalRow(Base):
    __tablename__ = "decision_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    release_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("release_decisions.id", ondelete="CASCADE"), index=True
    )
    approver_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    approval_type: Mapped[str] = mapped_column(String(48))
    comment: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RulePackRow(Base):
    __tablename__ = "rule_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), index=True)
    scope: Mapped[str] = mapped_column(String(80))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    published_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleDefinitionRow(Base):
    __tablename__ = "rule_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_pack_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rule_packs.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    condition_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntegrationConnectionRow(Base):
    __tablename__ = "integration_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), index=True)
    configuration_safe_json: Mapped[str] = mapped_column(Text, default="{}")
    credential_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ServiceAccountRow(Base):
    __tablename__ = "service_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiTokenRow(Base):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    service_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_accounts.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookSubscriptionRow(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    endpoint: Mapped[str] = mapped_column(String(500))
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    secret_hash: Mapped[str] = mapped_column(String(64))
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebhookDeliveryRow(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "event_id", name="uq_webhook_delivery_subscription_event"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProcessingJobRow(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(48), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    href: Mapped[str | None] = mapped_column(String(320), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class NotificationPreferenceRow(Base):
    __tablename__ = "notification_preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceSettingRow(Base):
    __tablename__ = "workspace_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    setting_key: Mapped[str] = mapped_column(String(100), index=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LegalHoldRow(Base):
    __tablename__ = "legal_holds"
    __table_args__ = (
        UniqueConstraint("organization_id", "shipment_id", name="uq_legal_hold_shipment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReferenceDataRow(Base):
    __tablename__ = "reference_data"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(200))
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScreeningRunRow(Base):
    __tablename__ = "screening_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    shipment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shipment_cases.id", ondelete="CASCADE"), index=True
    )
    party_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_parties.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(80))
    dataset: Mapped[str] = mapped_column(String(120))
    dataset_version: Mapped[str] = mapped_column(String(40))
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    result: Mapped[str] = mapped_column(String(32), index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    matched_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScreeningMatchRow(Base):
    __tablename__ = "screening_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    screening_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("screening_runs.id", ondelete="CASCADE"), index=True
    )
    matched_name: Mapped[str] = mapped_column(String(200))
    matched_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dataset_record_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    disposition: Mapped[str] = mapped_column(String(40), default="REQUIRES_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[str] = mapped_column(String(40), default="unknown")
    current_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    safe_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DomainEventRow(Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "event_type",
            "idempotency_key",
            name="uq_domain_event_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApiIdempotencyRow(Base):
    __tablename__ = "api_idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "service_account_id",
            "idempotency_key",
            name="uq_api_idempotency_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    service_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("service_accounts.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING")
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


def row_dict(row: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in exclude
    }


class OperationsRepository:
    def __init__(self, database_url: str, *, auto_create_schema: bool = True):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        connect_args = (
            {"check_same_thread": False, "timeout": 10} if database_url.startswith("sqlite") else {}
        )
        self.engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        if auto_create_schema:
            Base.metadata.create_all(self.engine)
        self.ensure_default_workspace()
        if auto_create_schema:
            self.ensure_core_policy()

    def ensure_default_workspace(self) -> str | None:
        """Provision the bootstrap workspace only when no organization exists.

        Existing tenants are never selected as an implicit runtime default and no
        rule pack is attributed to an arbitrary existing user.
        """
        with self.session_factory() as session:
            has_organization = session.scalar(select(OrganizationRow.id).limit(1))
            if has_organization is not None:
                return None
            now = now_utc()
            organization = OrganizationRow(
                id=str(uuid.uuid4()),
                name="GateGuard Operations",
                code="DEFAULT",
                created_at=now,
                updated_at=now,
            )
            session.add(organization)
            session.flush()
            session.add(
                FacilityRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization.id,
                    name="Primary facility",
                    code="PRIMARY",
                    country_code=None,
                    location=None,
                    timezone=organization.default_timezone,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            return organization.id

    def ensure_core_policy(self) -> None:
        """Seed one explicit published policy for local/test databases."""
        with self.session_factory() as session:
            if session.scalar(
                select(RulePackRow.id).where(RulePackRow.status == "PUBLISHED").limit(1)
            ):
                return
            now = now_utc()
            pack_id = str(uuid.uuid4())
            pack = RulePackRow(
                id=pack_id,
                organization_id=None,
                name="GateGuard Core Assurance Policy",
                version="2026.08.1",
                status="PUBLISHED",
                scope="GLOBAL",
                effective_from=now,
                effective_to=None,
                created_by="system",
                published_by=None,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(pack)
            session.add_all(
                RuleDefinitionRow(
                    id=str(uuid.uuid4()),
                    rule_pack_id=pack_id,
                    rule_id=rule_id,
                    name=name,
                    description=description,
                    condition_json=json.dumps(condition, sort_keys=True),
                    active=True,
                    created_at=now,
                )
                for rule_id, name, description, condition in (
                    (
                        "DOCS_REQUIRED",
                        "Required shipment documents",
                        "All active document requirements must have evidence.",
                        {"check_type": "DOCUMENT_REQUIREMENTS"},
                    ),
                    (
                        "DG_COMPLETE",
                        "Dangerous goods completeness",
                        "Dangerous goods declarations require complete identifiers.",
                        {"check_type": "DANGEROUS_GOODS"},
                    ),
                    (
                        "SCREENING_REVIEW",
                        "Party screening disposition",
                        "Missing or unresolved screening cannot authorize release.",
                        {"check_type": "PARTY_SCREENING"},
                    ),
                    (
                        "RISK_BLOCKING_ASSURANCE",
                        "Risk weight: blocking assurance",
                        "Scoring input for a persisted blocking assurance finding.",
                        {"risk_factor": "BLOCKING_ASSURANCE", "weight": 40},
                    ),
                    (
                        "RISK_MISSING_DOCUMENT",
                        "Risk weight: missing document",
                        "Scoring input for a missing required document.",
                        {"risk_factor": "MISSING_REQUIRED_DOCUMENT", "weight": 25},
                    ),
                    (
                        "RISK_HIGH_EXCEPTION",
                        "Risk weight: high exception",
                        "Scoring input for a high or critical exception.",
                        {"risk_factor": "HIGH_CRITICAL_EXCEPTION", "weight": 30},
                    ),
                    (
                        "RISK_DANGEROUS_GOODS",
                        "Risk weight: dangerous goods",
                        "Scoring input for incomplete dangerous goods evidence.",
                        {"risk_factor": "DANGEROUS_GOODS_INCOMPLETE", "weight": 20},
                    ),
                    (
                        "RISK_THRESHOLD_MEDIUM",
                        "Risk threshold: medium",
                        "Policy threshold.",
                        {"risk_level": "MEDIUM", "threshold": 25},
                    ),
                    (
                        "RISK_THRESHOLD_HIGH",
                        "Risk threshold: high",
                        "Policy threshold.",
                        {"risk_level": "HIGH", "threshold": 50},
                    ),
                    (
                        "RISK_THRESHOLD_CRITICAL",
                        "Risk threshold: critical",
                        "Policy threshold.",
                        {"risk_level": "CRITICAL", "threshold": 75},
                    ),
                )
            )
            session.commit()

    def organization_for(self, user: UserRow, requested_id: str | None = None) -> OrganizationRow:
        with self.session_factory() as session:
            stmt = (
                select(OrganizationRow)
                .join(
                    WorkspaceMembershipRow,
                    WorkspaceMembershipRow.organization_id == OrganizationRow.id,
                )
                .where(
                    WorkspaceMembershipRow.user_id == user.id,
                    WorkspaceMembershipRow.active.is_(True),
                    OrganizationRow.active.is_(True),
                )
            )
            if requested_id:
                stmt = stmt.where(OrganizationRow.id == requested_id)
            organization = session.scalar(stmt.order_by(OrganizationRow.created_at.asc()))
            if organization is None:
                raise GateGuardError(
                    "You do not have access to this workspace.", code="FORBIDDEN", status_code=403
                )
            return organization

    def membership_role_for(self, *, organization_id: str, user_id: str) -> str:
        with self.session_factory() as session:
            membership = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.organization_id == organization_id,
                    WorkspaceMembershipRow.user_id == user_id,
                    WorkspaceMembershipRow.active.is_(True),
                )
            )
            if membership is None:
                raise GateGuardError(
                    "You do not have access to this workspace.", code="FORBIDDEN", status_code=403
                )
            return membership.role

    def list_organizations(self, user: UserRow) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(OrganizationRow)
                    .join(
                        WorkspaceMembershipRow,
                        WorkspaceMembershipRow.organization_id == OrganizationRow.id,
                    )
                    .where(
                        WorkspaceMembershipRow.user_id == user.id,
                        WorkspaceMembershipRow.active.is_(True),
                        OrganizationRow.active.is_(True),
                    )
                    .order_by(OrganizationRow.name.asc())
                )
            )
            return [row_dict(row) for row in rows]

    def record_recent(
        self,
        *,
        organization_id: str,
        user_id: str,
        object_type: str,
        object_id: str,
        label: str,
        href: str,
    ) -> None:
        with self.session_factory() as session:
            old = session.scalar(
                select(RecentObjectRow).where(
                    RecentObjectRow.organization_id == organization_id,
                    RecentObjectRow.user_id == user_id,
                    RecentObjectRow.object_type == object_type,
                    RecentObjectRow.object_id == object_id,
                )
            )
            if old:
                old.viewed_at = now_utc()
            else:
                session.add(
                    RecentObjectRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        user_id=user_id,
                        object_type=object_type,
                        object_id=object_id,
                        label=label,
                        href=href,
                        viewed_at=now_utc(),
                    )
                )
            session.commit()

    def recents(
        self, *, organization_id: str, user_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(RecentObjectRow)
                    .where(
                        RecentObjectRow.organization_id == organization_id,
                        RecentObjectRow.user_id == user_id,
                    )
                    .order_by(RecentObjectRow.viewed_at.desc())
                    .limit(max(1, min(limit, 100)))
                )
            )
            return [row_dict(row) for row in rows]

    def search(
        self,
        *,
        organization_id: str,
        user: UserRow,
        workspace_role: str | None = None,
        query: str,
        limit: int = 20,
        types: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        term = f"%{query.strip()}%"
        bounded = max(1, min(limit, 50))
        effective_role = workspace_role or user.role
        result: list[dict[str, Any]] = []
        with self.session_factory() as session:
            shipments = list(
                session.scalars(
                    select(ShipmentCaseRow)
                    .where(
                        ShipmentCaseRow.organization_id == organization_id,
                        or_(
                            ShipmentCaseRow.internal_reference.ilike(term),
                            ShipmentCaseRow.external_reference.ilike(term),
                            ShipmentCaseRow.destination.ilike(term),
                        ),
                    )
                    .order_by(ShipmentCaseRow.updated_at.desc())
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "shipment",
                    "id": row.id,
                    "label": row.internal_reference,
                    "description": f"{row.origin} → {row.destination}",
                    "href": f"/shipments/{row.id}",
                }
                for row in shipments
            )
            documents = list(
                session.execute(
                    select(ShipmentDocumentRow, ShipmentCaseRow)
                    .join(ShipmentCaseRow, ShipmentCaseRow.id == ShipmentDocumentRow.shipment_id)
                    .outerjoin(
                        DocumentVersionRow,
                        DocumentVersionRow.id == ShipmentDocumentRow.current_version_id,
                    )
                    .where(
                        ShipmentDocumentRow.organization_id == organization_id,
                        or_(
                            ShipmentDocumentRow.document_type.ilike(term),
                            ShipmentDocumentRow.document_reference.ilike(term),
                            DocumentVersionRow.filename.ilike(term),
                        ),
                    )
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "document",
                    "id": doc.id,
                    "label": doc.document_reference or doc.document_type,
                    "description": shipment.internal_reference,
                    "href": f"/shipments/{shipment.id}",
                }
                for doc, shipment in documents
            )
            parties = list(
                session.scalars(
                    select(TradePartyRow)
                    .where(
                        TradePartyRow.organization_id == organization_id,
                        TradePartyRow.legal_name.ilike(term),
                    )
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "party",
                    "id": party.id,
                    "label": party.legal_name,
                    "description": party.country_code or "Party",
                    "href": "/parties",
                }
                for party in parties
            )
            items = list(
                session.scalars(
                    select(ShipmentItemRow)
                    .where(
                        ShipmentItemRow.organization_id == organization_id,
                        or_(
                            ShipmentItemRow.sku.ilike(term),
                            ShipmentItemRow.description.ilike(term),
                        ),
                    )
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "product",
                    "id": item.id,
                    "label": item.sku or item.description,
                    "description": "Shipment item",
                    "href": "/products",
                }
                for item in items
            )
            exceptions = list(
                session.scalars(
                    select(ShipmentExceptionRow)
                    .where(
                        ShipmentExceptionRow.organization_id == organization_id,
                        ShipmentExceptionRow.summary.ilike(term),
                    )
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "exception",
                    "id": item.id,
                    "label": item.summary,
                    "description": item.status,
                    "href": "/exceptions",
                }
                for item in exceptions
            )
            releases = list(
                session.execute(
                    select(ReleaseDecisionRow, ShipmentCaseRow)
                    .join(ShipmentCaseRow, ShipmentCaseRow.id == ReleaseDecisionRow.shipment_id)
                    .where(
                        ShipmentCaseRow.organization_id == organization_id,
                        ReleaseDecisionRow.reason.ilike(term),
                    )
                    .limit(bounded)
                )
            )
            result.extend(
                {
                    "type": "release",
                    "id": release.id,
                    "label": shipment.internal_reference,
                    "description": release.decision,
                    "href": "/releases",
                }
                for release, shipment in releases
            )
            if effective_role in {UserRole.ADMIN.value, UserRole.SUPERVISOR.value}:
                users = list(
                    session.scalars(
                        select(UserRow)
                        .join(WorkspaceMembershipRow, WorkspaceMembershipRow.user_id == UserRow.id)
                        .where(
                            WorkspaceMembershipRow.organization_id == organization_id,
                            or_(UserRow.display_name.ilike(term), UserRow.email.ilike(term)),
                        )
                        .limit(bounded)
                    )
                )
                result.extend(
                    {
                        "type": "person",
                        "id": item.id,
                        "label": item.display_name,
                        "description": item.email,
                        "href": "/settings/people",
                    }
                    for item in users
                )
                if effective_role == UserRole.ADMIN.value:
                    packs = list(
                        session.scalars(
                            select(RulePackRow)
                            .where(
                                RulePackRow.organization_id == organization_id,
                                RulePackRow.name.ilike(term),
                            )
                            .limit(bounded)
                        )
                    )
                    result.extend(
                        {
                            "type": "rule_pack",
                            "id": pack.id,
                            "label": pack.name,
                            "description": f"Version {pack.version}",
                            "href": "/governance/rule-packs",
                        }
                        for pack in packs
                    )
                    connections = list(
                        session.scalars(
                            select(IntegrationConnectionRow)
                            .where(
                                IntegrationConnectionRow.organization_id == organization_id,
                                IntegrationConnectionRow.name.ilike(term),
                            )
                            .limit(bounded)
                        )
                    )
                    result.extend(
                        {
                            "type": "integration",
                            "id": connection.id,
                            "label": connection.name,
                            "description": connection.status,
                            "href": "/integrations/connections",
                        }
                        for connection in connections
                    )
        if types:
            result = [item for item in result if item["type"] in types]
        return result[:bounded]

    def list_parties(
        self, *, organization_id: str, query: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = select(TradePartyRow).where(TradePartyRow.organization_id == organization_id)
            if query:
                term = f"%{query.strip()}%"
                stmt = stmt.where(
                    or_(
                        TradePartyRow.legal_name.ilike(term),
                        TradePartyRow.external_identifier.ilike(term),
                    )
                )
            rows = list(
                session.scalars(
                    stmt.order_by(TradePartyRow.updated_at.desc()).limit(max(1, min(limit, 200)))
                )
            )
            output = []
            for row in rows:
                shipment_count = (
                    session.scalar(
                        select(func.count(ShipmentPartyRow.id)).where(
                            ShipmentPartyRow.party_id == row.id
                        )
                    )
                    or 0
                )
                latest_screening = session.scalar(
                    select(ScreeningRunRow)
                    .where(
                        ScreeningRunRow.organization_id == organization_id,
                        ScreeningRunRow.party_id == row.id,
                    )
                    .order_by(ScreeningRunRow.screened_at.desc())
                )
                output.append(
                    {
                        **row_dict(row),
                        "shipment_count": int(shipment_count),
                        "screening": (
                            latest_screening.result
                            if latest_screening is not None
                            else "NOT_RUN"
                        ),
                    }
                )
            return output

    def create_party(
        self, *, organization_id: str, user: UserRow, payload: dict[str, Any]
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            party = TradePartyRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                legal_name=str(payload["legal_name"]).strip(),
                trade_name=payload.get("trade_name"),
                country_code=payload.get("country_code"),
                address=payload.get("address"),
                city=payload.get("city"),
                region=payload.get("region"),
                postal_code=payload.get("postal_code"),
                email=payload.get("email"),
                phone=payload.get("phone"),
                tax_identifier=payload.get("tax_identifier"),
                external_identifier=payload.get("external_identifier"),
                created_at=now,
                updated_at=now,
            )
            session.add(party)
            session.flush()
            if payload.get("shipment_id"):
                shipment = session.scalar(
                    select(ShipmentCaseRow).where(
                        ShipmentCaseRow.id == payload["shipment_id"],
                        ShipmentCaseRow.organization_id == organization_id,
                    )
                )
                if shipment is None:
                    raise NotFoundError("Shipment was not found in this workspace.")
                session.add(
                    ShipmentPartyRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        shipment_id=shipment.id,
                        party_id=party.id,
                        role=str(payload.get("role") or "OTHER"),
                        created_at=now,
                    )
                )
            if payload.get("external_identifier"):
                session.add(
                    PartyIdentifierRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        party_id=party.id,
                        identifier_type="EXTERNAL",
                        identifier_value=str(payload["external_identifier"]),
                        created_at=now,
                    )
                )
            session.commit()
            session.refresh(party)
            return row_dict(party)

    def list_items(
        self, *, organization_id: str, query: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = (
                select(ShipmentItemRow, ShipmentCaseRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ShipmentItemRow.shipment_id)
                .where(ShipmentItemRow.organization_id == organization_id)
            )
            if query:
                term = f"%{query.strip()}%"
                stmt = stmt.where(
                    or_(
                        ShipmentItemRow.sku.ilike(term),
                        ShipmentItemRow.description.ilike(term),
                        ShipmentCaseRow.internal_reference.like(term),
                    )
                )
            rows = list(
                session.execute(
                    stmt.order_by(ShipmentItemRow.updated_at.desc()).limit(max(1, min(limit, 200)))
                )
            )
            return [
                {**row_dict(item), "shipment_reference": shipment.internal_reference}
                for item, shipment in rows
            ]

    def create_item(self, *, organization_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == payload["shipment_id"],
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            item = ShipmentItemRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment.id,
                line_number=int(payload["line_number"]),
                sku=payload.get("sku"),
                description=str(payload["description"]),
                quantity=float(payload.get("quantity") or 0),
                unit_of_measure=str(payload.get("unit_of_measure") or "unit"),
                unit_price=payload.get("unit_price"),
                currency=payload.get("currency"),
                line_total=payload.get("line_total"),
                country_of_origin=payload.get("country_of_origin"),
                hs_code=payload.get("hs_code"),
                gross_weight=payload.get("gross_weight"),
                net_weight=payload.get("net_weight"),
                dangerous_goods=bool(payload.get("dangerous_goods")),
                un_number=payload.get("un_number"),
                proper_shipping_name=payload.get("proper_shipping_name"),
                hazard_class=payload.get("hazard_class"),
                packing_group=payload.get("packing_group"),
                special_handling=payload.get("special_handling"),
                package_count=payload.get("package_count"),
                created_at=now,
                updated_at=now,
            )
            session.add(item)
            shipment.updated_at = now
            session.commit()
            session.refresh(item)
            return row_dict(item)

    def list_transport(
        self, *, organization_id: str, shipment_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = select(TransportLegRow).where(TransportLegRow.organization_id == organization_id)
            if shipment_id:
                stmt = stmt.where(TransportLegRow.shipment_id == shipment_id)
            return [
                row_dict(row)
                for row in session.scalars(stmt.order_by(TransportLegRow.sequence.asc()))
            ]

    def create_transport(self, *, organization_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == payload["shipment_id"],
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            leg = TransportLegRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment.id,
                sequence=int(payload.get("sequence") or 1),
                mode=str(payload["mode"]),
                carrier=payload.get("carrier"),
                origin=payload.get("origin"),
                destination=payload.get("destination"),
                planned_departure=payload.get("planned_departure"),
                planned_arrival=payload.get("planned_arrival"),
                actual_departure=payload.get("actual_departure"),
                actual_arrival=payload.get("actual_arrival"),
                vessel=payload.get("vessel"),
                voyage=payload.get("voyage"),
                flight=payload.get("flight"),
                vehicle_reference=payload.get("vehicle_reference"),
                created_at=now,
            )
            session.add(leg)
            shipment.updated_at = now
            session.commit()
            session.refresh(leg)
            return row_dict(leg)

    def list_documents(
        self,
        *,
        organization_id: str,
        query: str | None = None,
        status: str | None = None,
        document_type: str | None = None,
        extraction_status: str | None = None,
        shipment_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = (
                select(ShipmentDocumentRow, ShipmentCaseRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ShipmentDocumentRow.shipment_id)
                .where(ShipmentDocumentRow.organization_id == organization_id)
            )
            if query:
                term = f"%{query.strip()}%"
                stmt = stmt.where(
                    or_(
                        ShipmentDocumentRow.document_type.like(term),
                        ShipmentCaseRow.internal_reference.like(term),
                    )
                )
            if status:
                stmt = stmt.where(ShipmentDocumentRow.status == status)
            if document_type:
                stmt = stmt.where(ShipmentDocumentRow.document_type == document_type.upper())
            if shipment_id:
                stmt = stmt.where(ShipmentDocumentRow.shipment_id == shipment_id)
            rows = list(
                session.execute(
                    stmt.order_by(ShipmentDocumentRow.updated_at.desc()).limit(
                        max(1, min(limit, 200))
                    )
                )
            )
            output = []
            for document, shipment in rows:
                version = (
                    session.scalar(
                        select(DocumentVersionRow).where(
                            DocumentVersionRow.id == document.current_version_id
                        )
                    )
                    if document.current_version_id
                    else None
                )
                item = {
                    **row_dict(document),
                    "shipment_reference": shipment.internal_reference,
                    "version": row_dict(version, exclude={"storage_key"}) if version else None,
                    "extraction_recorded_at": (
                        document.updated_at
                        if version and version.extraction_status in {"EXTRACTED", "NEEDS_REVIEW"}
                        else None
                    ),
                }
                if extraction_status and (
                    not version or version.extraction_status != extraction_status
                ):
                    continue
                output.append(item)
            return output

    def detail(self, *, organization_id: str, shipment_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            parties = list(
                session.execute(
                    select(ShipmentPartyRow, TradePartyRow)
                    .join(TradePartyRow, TradePartyRow.id == ShipmentPartyRow.party_id)
                    .where(ShipmentPartyRow.shipment_id == shipment_id)
                )
            )
            docs = self.list_documents(organization_id=organization_id, shipment_id=shipment_id)
            items = [
                row_dict(row)
                for row in session.scalars(
                    select(ShipmentItemRow)
                    .where(ShipmentItemRow.shipment_id == shipment_id)
                    .order_by(ShipmentItemRow.line_number.asc())
                )
            ]
            legs = [
                row_dict(row)
                for row in session.scalars(
                    select(TransportLegRow)
                    .where(TransportLegRow.shipment_id == shipment_id)
                    .order_by(TransportLegRow.sequence.asc())
                )
            ]
            checks = [
                row_dict(row) | {"details": json.loads(row.details_json)}
                for row in session.scalars(
                    select(AssuranceCheckRow)
                    .where(AssuranceCheckRow.shipment_id == shipment_id)
                    .order_by(AssuranceCheckRow.created_at.desc())
                )
            ]
            exceptions = [
                row_dict(row)
                for row in session.scalars(
                    select(ShipmentExceptionRow)
                    .where(ShipmentExceptionRow.shipment_id == shipment_id)
                    .order_by(ShipmentExceptionRow.created_at.desc())
                )
            ]
            open_tasks = (
                session.scalar(
                    select(func.count(ReviewTaskRow.id)).where(
                        ReviewTaskRow.shipment_id == shipment_id,
                        ReviewTaskRow.status != "RESOLVED",
                    )
                )
                or 0
            )
            return {
                "shipment": row_dict(shipment) | {"open_tasks": int(open_tasks)},
                "parties": [
                    {**row_dict(link), "party": row_dict(party)} for link, party in parties
                ],
                "documents": docs,
                "items": items,
                "transport": legs,
                "checks": checks,
                "exceptions": exceptions,
                "release_gate": self.release_gate(session, shipment_id),
                "risk_factors": json.loads(shipment.risk_factors_json or "[]"),
            }

    def release_gate(self, session: Session, shipment_id: str) -> list[dict[str, Any]]:
        evaluations = list(
            session.execute(
                select(RequirementEvaluationRow, DocumentRequirementRow)
                .join(
                    DocumentRequirementRow,
                    DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                )
                .where(RequirementEvaluationRow.shipment_id == shipment_id)
            )
        )
        missing_requirements = [
            requirement.name
            for evaluation, requirement in evaluations
            if requirement.status in {"REQUIRED", "ACTIVE"}
            and evaluation.result not in {"PROVIDED", "CLEAR", "NOT_APPLICABLE"}
        ]
        checks = list(
            session.scalars(
                select(AssuranceCheckRow)
                .where(AssuranceCheckRow.shipment_id == shipment_id)
                .order_by(AssuranceCheckRow.created_at.desc())
            )
        )
        latest: dict[str, AssuranceCheckRow] = {}
        for check in checks:
            latest.setdefault(check.check_type, check)
        exceptions = (
            session.scalar(
                select(func.count(ShipmentExceptionRow.id)).where(
                    ShipmentExceptionRow.shipment_id == shipment_id,
                    ShipmentExceptionRow.status.not_in(["RESOLVED", "CANCELLED"]),
                )
            )
            or 0
        )

        def state(condition: bool, review: bool = False) -> str:
            return "CLEAR" if condition else "REVIEW" if review else "BLOCKED"

        document_state = "BLOCKED" if missing_requirements else "CLEAR" if evaluations else "REVIEW"
        latest_decision = session.scalar(
            select(ReleaseDecisionRow)
            .where(ReleaseDecisionRow.shipment_id == shipment_id)
            .order_by(ReleaseDecisionRow.created_at.desc())
        )
        approval_state = "NOT_REQUESTED"
        if latest_decision and latest_decision.invalidated_at is None:
            approval_state = (
                "AUTHORIZED"
                if session.scalar(
                    select(DecisionApprovalRow.id).where(
                        DecisionApprovalRow.release_decision_id == latest_decision.id
                    )
                )
                else "PENDING_SECOND_APPROVAL"
                if latest_decision.decision == "AUTHORIZE"
                else "HOLD"
            )
        return [
            {"key": "documents", "label": "Required documents", "state": document_state},
            {
                "key": "reconciliation",
                "label": "Document reconciliation",
                "state": latest.get("DOCUMENT_RECONCILIATION").status
                if latest.get("DOCUMENT_RECONCILIATION")
                else "REVIEW",
            },
            {
                "key": "trusted_source",
                "label": "Trusted source",
                "state": latest.get("TRUSTED_REFERENCE").status
                if latest.get("TRUSTED_REFERENCE")
                else "REVIEW",
            },
            {
                "key": "screening",
                "label": "Party screening",
                "state": latest.get("PARTY_SCREENING").status
                if latest.get("PARTY_SCREENING")
                else "N/A",
            },
            {
                "key": "dangerous_goods",
                "label": "Dangerous goods",
                "state": latest.get("DANGEROUS_GOODS").status
                if latest.get("DANGEROUS_GOODS")
                else "N/A",
            },
            {
                "key": "exceptions",
                "label": "Open exceptions",
                "state": state(exceptions == 0, review=exceptions > 0),
            },
            {"key": "approvals", "label": "Approvals", "state": approval_state},
        ]

    def release_gate_snapshot(self, *, organization_id: str, shipment_id: str) -> dict[str, Any]:
        """Return the canonical release decision snapshot used by UI and dispatch."""
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            evaluations = list(
                session.execute(
                    select(RequirementEvaluationRow, DocumentRequirementRow)
                    .join(
                        DocumentRequirementRow,
                        DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                    )
                    .where(
                        RequirementEvaluationRow.organization_id == organization_id,
                        RequirementEvaluationRow.shipment_id == shipment_id,
                    )
                )
            )
            requirements = [
                {
                    "id": requirement.id,
                    "name": requirement.name,
                    "result": evaluation.result,
                    "status": requirement.status,
                    "rule_pack_version": evaluation.rule_pack_version,
                }
                for evaluation, requirement in evaluations
            ]
            missing = [
                item["name"]
                for item in requirements
                if item["status"] in {"REQUIRED", "ACTIVE"}
                and item["result"] not in {"PROVIDED", "CLEAR", "NOT_APPLICABLE"}
            ]
            latest_checks: dict[str, AssuranceCheckRow] = {}
            for check in session.scalars(
                select(AssuranceCheckRow)
                .where(
                    AssuranceCheckRow.organization_id == organization_id,
                    AssuranceCheckRow.shipment_id == shipment_id,
                )
                .order_by(AssuranceCheckRow.created_at.desc())
            ):
                latest_checks.setdefault(check.check_type, check)
            blocking_checks = [
                check.check_type
                for check in latest_checks.values()
                if check.status in {"HOLD", "REVIEW", "PENDING", "RUNNING", "FAILED"}
            ]
            blocking_exceptions = [
                item.summary
                for item in session.scalars(
                    select(ShipmentExceptionRow).where(
                        ShipmentExceptionRow.organization_id == organization_id,
                        ShipmentExceptionRow.shipment_id == shipment_id,
                        ShipmentExceptionRow.status.not_in(["RESOLVED", "CANCELLED"]),
                    )
                )
                if item.severity in {"HIGH", "CRITICAL"}
            ]
            open_tasks = int(
                session.scalar(
                    select(func.count(ReviewTaskRow.id)).where(
                        ReviewTaskRow.organization_id == organization_id,
                        ReviewTaskRow.shipment_id == shipment_id,
                        ReviewTaskRow.status != "RESOLVED",
                    )
                )
                or 0
            )
            reference = session.scalar(
                select(TrustedShipmentReferenceRow).where(
                    TrustedShipmentReferenceRow.organization_id == organization_id,
                    TrustedShipmentReferenceRow.shipment_id == shipment_id,
                )
            )
            current = build_release_snapshot(
                missing_requirements=missing,
                blocking_checks=blocking_checks,
                blocking_exceptions=blocking_exceptions,
                open_tasks=open_tasks,
                trusted_reference_version=reference.version if reference else None,
                trusted_reference_hash=reference.content_hash if reference else None,
                assurance_versions={
                    check_type: (check.status, check.source_version)
                    for check_type, check in latest_checks.items()
                },
            )
            latest_decision = session.scalar(
                select(ReleaseDecisionRow)
                .where(
                    ReleaseDecisionRow.organization_id == organization_id,
                    ReleaseDecisionRow.shipment_id == shipment_id,
                )
                .order_by(ReleaseDecisionRow.created_at.desc())
            )
            approvals = []
            if latest_decision:
                approvals = [
                    {
                        "id": approval.id,
                        "approver_user_id": approval.approver_user_id,
                        "approval_type": approval.approval_type,
                        "approved_at": approval.approved_at,
                    }
                    for approval in session.scalars(
                        select(DecisionApprovalRow).where(
                            DecisionApprovalRow.organization_id == organization_id,
                            DecisionApprovalRow.release_decision_id == latest_decision.id,
                        )
                    )
                ]
            approval_state = "NOT_REQUESTED"
            if latest_decision and latest_decision.invalidated_at is None:
                approval_state = (
                    "AUTHORIZED"
                    if shipment.status == ShipmentStatus.RELEASE_AUTHORIZED.value
                    else "PENDING_SECOND_APPROVAL"
                    if latest_decision.decision == "AUTHORIZE"
                    else "HOLD"
                )
            policy = self._published_policy(session, organization_id=organization_id, now=now_utc())
            blockers = [
                *({"code": "MISSING_REQUIREMENT", "detail": item} for item in missing),
                *({"code": "BLOCKING_CHECK", "detail": item} for item in blocking_checks),
                *({"code": "BLOCKING_EXCEPTION", "detail": item} for item in blocking_exceptions),
            ]
            if open_tasks:
                blockers.append({"code": "OPEN_REVIEW_TASK", "detail": str(open_tasks)})
            return {
                "shipment_id": shipment_id,
                "status": "BLOCKED" if blockers else "CLEAR",
                "blockers": blockers,
                "requirements": requirements,
                "gate": self.release_gate(session, shipment_id),
                "latest_checks": [
                    row_dict(check) | {"details": json.loads(check.details_json or "{}")}
                    for check in latest_checks.values()
                ],
                "approval_state": approval_state,
                "approvals": approvals,
                "evidence_hash": snapshot_hash(current),
                "snapshot": current,
                "policy": {"id": policy.id, "version": policy.version} if policy else None,
                "latest_decision": row_dict(latest_decision) if latest_decision else None,
            }

    def list_checks(
        self,
        *,
        organization_id: str,
        check_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = (
                select(AssuranceCheckRow, ShipmentCaseRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == AssuranceCheckRow.shipment_id)
                .where(AssuranceCheckRow.organization_id == organization_id)
            )
            if check_type:
                stmt = stmt.where(AssuranceCheckRow.check_type == check_type)
            if status:
                stmt = stmt.where(AssuranceCheckRow.status == status)
            rows = list(
                session.execute(
                    stmt.order_by(AssuranceCheckRow.created_at.desc()).limit(
                        max(1, min(limit, 200))
                    )
                )
            )
            return [
                {
                    **row_dict(check),
                    "details": json.loads(check.details_json),
                    "shipment_reference": shipment.internal_reference,
                }
                for check, shipment in rows
            ]

    def list_exceptions(
        self,
        *,
        organization_id: str,
        status: str | None = None,
        mine: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = (
                select(ShipmentExceptionRow, ShipmentCaseRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ShipmentExceptionRow.shipment_id)
                .where(ShipmentExceptionRow.organization_id == organization_id)
            )
            if status:
                stmt = stmt.where(ShipmentExceptionRow.status == status)
            if mine:
                stmt = stmt.where(ShipmentExceptionRow.assigned_to == mine)
            rows = list(
                session.execute(
                    stmt.order_by(ShipmentExceptionRow.created_at.desc()).limit(
                        max(1, min(limit, 200))
                    )
                )
            )
            return [
                {**row_dict(exc), "shipment_reference": shipment.internal_reference}
                for exc, shipment in rows
            ]

    def list_releases(self, *, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = list(
                session.execute(
                    select(ReleaseDecisionRow, ShipmentCaseRow, UserRow)
                    .join(ShipmentCaseRow, ShipmentCaseRow.id == ReleaseDecisionRow.shipment_id)
                    .join(UserRow, UserRow.id == ReleaseDecisionRow.decided_by)
                    .where(ShipmentCaseRow.organization_id == organization_id)
                    .order_by(ReleaseDecisionRow.created_at.desc())
                    .limit(max(1, min(limit, 200)))
                )
            )
            return [
                {
                    **row_dict(decision),
                    "shipment_reference": shipment.internal_reference,
                    "issued_by_name": user.display_name,
                }
                for decision, shipment, user in rows
            ]

    def list_jobs(
        self, *, organization_id: str, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = select(ProcessingJobRow).where(
                ProcessingJobRow.organization_id == organization_id
            )
            if status:
                stmt = stmt.where(ProcessingJobRow.status == status)
            return [
                row_dict(row)
                for row in session.scalars(
                    stmt.order_by(ProcessingJobRow.queued_at.desc()).limit(max(1, min(limit, 200)))
                )
            ]

    def retry_job(self, *, organization_id: str, job_id: str) -> dict[str, Any]:
        """Requeue a failed job only after verifying its workspace boundary."""
        now = now_utc()
        with self.session_factory() as session:
            job = session.scalar(
                select(ProcessingJobRow).where(
                    ProcessingJobRow.id == job_id,
                    ProcessingJobRow.organization_id == organization_id,
                )
            )
            if job is None:
                raise NotFoundError("Processing job was not found in this workspace.")
            if job.status not in {"FAILED", "DEAD_LETTER"}:
                raise GateGuardError(
                    "Only failed or dead-letter jobs can be retried manually.",
                    code="JOB_NOT_RETRYABLE",
                    status_code=409,
                )
            job.status = "QUEUED"
            job.attempts = 0
            job.started_at = None
            job.completed_at = None
            job.heartbeat_at = None
            job.next_attempt_at = now
            job.error_code = None
            job.safe_error = None
            session.commit()
            session.refresh(job)
            return row_dict(job)

    def list_connections(self, *, organization_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            return [
                {
                    **row_dict(row, exclude={"configuration_safe_json", "credential_reference"}),
                    "configuration": json.loads(row.configuration_safe_json or "{}"),
                    "credential_configured": bool(row.credential_reference),
                }
                for row in session.scalars(
                    select(IntegrationConnectionRow)
                    .where(IntegrationConnectionRow.organization_id == organization_id)
                    .order_by(IntegrationConnectionRow.updated_at.desc())
                )
            ]

    def list_webhooks(self, *, organization_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(WebhookSubscriptionRow)
                    .where(WebhookSubscriptionRow.organization_id == organization_id)
                    .order_by(WebhookSubscriptionRow.updated_at.desc())
                )
            )
            return [
                {
                    **row_dict(row, exclude={"secret_hash", "secret_ciphertext"}),
                    "events": json.loads(row.events_json),
                    "secret_configured": bool(row.secret_hash),
                    "secret_reveal": "one_time_on_create",
                    "delivery_capability": "QUEUED_DELIVERY",
                }
                for row in rows
            ]

    def list_reference_data(
        self,
        *,
        organization_id: str,
        category: str | None = None,
        query: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            stmt = select(ReferenceDataRow).where(
                ReferenceDataRow.organization_id == organization_id
            )
            if category:
                stmt = stmt.where(ReferenceDataRow.category == category.upper())
            if active_only:
                stmt = stmt.where(ReferenceDataRow.active.is_(True))
            if query:
                term = f"%{query.strip()}%"
                stmt = stmt.where(
                    or_(ReferenceDataRow.code.like(term), ReferenceDataRow.label.like(term))
                )
            rows = session.scalars(
                stmt.order_by(ReferenceDataRow.category.asc(), ReferenceDataRow.code.asc()).limit(
                    max(1, min(limit, 500))
                )
            )
            return [
                {**row_dict(row), "metadata": json.loads(row.metadata_json or "{}")} for row in rows
            ]

    def create_reference_data(
        self, *, organization_id: str, user: UserRow, payload: dict[str, Any]
    ) -> dict[str, Any]:
        category = str(payload["category"]).strip().upper()
        code = str(payload["code"]).strip().upper()
        label = " ".join(str(payload["label"]).split())
        if not category or not code or not label:
            raise GateGuardError(
                "Category, code, and label are required.",
                code="VALIDATION_ERROR",
                status_code=422,
            )
        now = now_utc()
        with self.session_factory() as session:
            duplicate = session.scalar(
                select(ReferenceDataRow).where(
                    ReferenceDataRow.organization_id == organization_id,
                    ReferenceDataRow.category == category,
                    ReferenceDataRow.code == code,
                )
            )
            if duplicate:
                raise GateGuardError(
                    "That reference code already exists in this category.",
                    code="DUPLICATE_REFERENCE_DATA",
                    status_code=409,
                )
            row = ReferenceDataRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                category=category,
                code=code,
                label=label,
                metadata_json=json.dumps(payload.get("metadata", {})),
                source=str(payload.get("source") or "Workspace maintained").strip(),
                version=str(payload.get("version") or "1").strip(),
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="reference_data.created",
                    entity_type="reference_data",
                    entity_id=row.id,
                    payload_json=json.dumps({"category": category, "code": code}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(row)
            return {**row_dict(row), "metadata": json.loads(row.metadata_json)}

    def rule_pack_detail(self, *, organization_id: str, rule_pack_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            pack = session.scalar(
                select(RulePackRow).where(
                    RulePackRow.id == rule_pack_id,
                    or_(
                        RulePackRow.organization_id == organization_id,
                        RulePackRow.organization_id.is_(None),
                    ),
                )
            )
            if pack is None:
                raise NotFoundError("Rule pack was not found in this workspace.")
            rules = list(
                session.scalars(
                    select(RuleDefinitionRow)
                    .where(RuleDefinitionRow.rule_pack_id == pack.id)
                    .order_by(RuleDefinitionRow.rule_id.asc())
                )
            )
            return {
                "rule_pack": row_dict(pack),
                "rules": [
                    {**row_dict(rule), "condition": json.loads(rule.condition_json or "{}")}
                    for rule in rules
                ],
            }

    def publish_rule_pack(
        self, *, organization_id: str, rule_pack_id: str, user: UserRow
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            pack = session.scalar(
                select(RulePackRow).where(
                    RulePackRow.id == rule_pack_id,
                    or_(
                        RulePackRow.organization_id == organization_id,
                        RulePackRow.organization_id.is_(None),
                    ),
                )
            )
            if pack is None:
                raise NotFoundError("Rule pack was not found in this workspace.")
            if pack.organization_id is None:
                raise GateGuardError(
                    "Shared policy packs are platform-managed and cannot be published "
                    "from a workspace.",
                    code="SHARED_POLICY_IMMUTABLE",
                    status_code=409,
                )
            if pack.status == "PUBLISHED":
                raise GateGuardError(
                    "Published rule packs are immutable.",
                    code="IMMUTABLE_RULE_PACK",
                    status_code=409,
                )
            pack.status = "PUBLISHED"
            pack.published_by = user.id
            pack.published_at = now
            pack.updated_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="rule_pack.published",
                    entity_type="rule_pack",
                    entity_id=pack.id,
                    payload_json=json.dumps({"version": pack.version}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(pack)
            return row_dict(pack)

    def simulate_rule_pack(
        self, *, organization_id: str, rule_pack_id: str, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        detail = self.rule_pack_detail(organization_id=organization_id, rule_pack_id=rule_pack_id)
        context = input_data or {}
        results = []
        for rule in detail["rules"]:
            condition = rule["condition"]
            matches = all(context.get(str(key)) == value for key, value in condition.items())
            results.append(
                {
                    "rule_id": rule["rule_id"],
                    "matched": matches,
                    "result": "APPLIES" if matches else "NOT_APPLICABLE",
                }
            )
        return {"rule_pack": detail["rule_pack"], "results": results, "mutated": False}

    def list_notifications(
        self, *, organization_id: str, user_id: str, unread_only: bool = False, limit: int = 50
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            stmt = select(NotificationRow).where(
                NotificationRow.organization_id == organization_id,
                NotificationRow.user_id == user_id,
            )
            if unread_only:
                stmt = stmt.where(NotificationRow.read_at.is_(None))
            rows = list(
                session.scalars(
                    stmt.order_by(NotificationRow.created_at.desc()).limit(max(1, min(limit, 100)))
                )
            )
            unread = (
                session.scalar(
                    select(func.count(NotificationRow.id)).where(
                        NotificationRow.organization_id == organization_id,
                        NotificationRow.user_id == user_id,
                        NotificationRow.read_at.is_(None),
                    )
                )
                or 0
            )
            return {"unread": int(unread), "items": [row_dict(row) for row in rows]}

    def mark_notification_read(
        self, *, organization_id: str, user_id: str, notification_id: str
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            row = session.scalar(
                select(NotificationRow).where(
                    NotificationRow.id == notification_id,
                    NotificationRow.organization_id == organization_id,
                    NotificationRow.user_id == user_id,
                )
            )
            if row is None:
                raise NotFoundError("Notification was not found in this workspace.")
            row.read_at = row.read_at or now_utc()
            session.commit()
            session.refresh(row)
            return row_dict(row)

    def settings(self, *, organization_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            organization = session.get(OrganizationRow, organization_id)
            rows = list(
                session.scalars(
                    select(WorkspaceSettingRow).where(
                        WorkspaceSettingRow.organization_id == organization_id
                    )
                )
            )
            values = {row.setting_key: json.loads(row.value_json) for row in rows}
            return {
                "organization": row_dict(organization) if organization else None,
                "settings": values,
            }

    def save_settings(
        self, *, organization_id: str, user: UserRow, values: dict[str, Any]
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            organization = session.get(OrganizationRow, organization_id)
            if organization is None:
                raise NotFoundError("Workspace was not found.")
            for key, value in values.items():
                if key in {"name", "default_timezone", "default_locale", "default_currency"}:
                    field = "name" if key == "name" else key
                    setattr(organization, field, str(value).strip())
                    organization.updated_at = now
                    continue
                if key == "review_policy":
                    value = normalize_review_policy(value)
                if key == "retention":
                    value = normalize_retention_policy(value)
                setting = session.scalar(
                    select(WorkspaceSettingRow).where(
                        WorkspaceSettingRow.organization_id == organization_id,
                        WorkspaceSettingRow.setting_key == key,
                    )
                )
                if setting is None:
                    session.add(
                        WorkspaceSettingRow(
                            id=str(uuid.uuid4()),
                            organization_id=organization_id,
                            setting_key=key,
                            value_json=json.dumps(value),
                            updated_by=user.id,
                            updated_at=now,
                        )
                    )
                else:
                    setting.value_json = json.dumps(value)
                    setting.updated_by = user.id
                    setting.updated_at = now
            session.commit()
        return self.settings(organization_id=organization_id)

    def retention_policy(self, *, organization_id: str) -> dict[str, int]:
        values = self.settings(organization_id=organization_id).get("settings", {})
        return normalize_retention_policy(values.get("retention", {}))

    def retention_dry_run(self, *, organization_id: str) -> dict[str, Any]:
        policy = self.retention_policy(organization_id=organization_id)
        now = now_utc()
        cutoffs = {key: now - timedelta(days=days) for key, days in policy.items()}
        with self.session_factory() as session:
            held_ids = set(
                session.scalars(
                    select(LegalHoldRow.shipment_id).where(
                        LegalHoldRow.organization_id == organization_id,
                        LegalHoldRow.active.is_(True),
                    )
                )
            )
            audit_query = select(AuditEventRow).where(
                AuditEventRow.organization_id == organization_id,
                AuditEventRow.created_at < cutoffs["audit_days"],
            )
            if held_ids:
                audit_query = audit_query.where(~AuditEventRow.entity_id.in_(held_ids))
            audit_count = int(len(list(session.scalars(audit_query))))
            job_count = int(
                session.scalar(
                    select(func.count(ProcessingJobRow.id)).where(
                        ProcessingJobRow.organization_id == organization_id,
                        ProcessingJobRow.queued_at < cutoffs["job_days"],
                        ProcessingJobRow.status.in_(["SUCCEEDED", "FAILED", "DEAD_LETTER"]),
                    )
                )
                or 0
            )
            webhook_count = int(
                session.scalar(
                    select(func.count(WebhookDeliveryRow.id)).where(
                        WebhookDeliveryRow.organization_id == organization_id,
                        WebhookDeliveryRow.created_at < cutoffs["webhook_days"],
                        WebhookDeliveryRow.status.in_(["DELIVERED", "FAILED"]),
                    )
                )
                or 0
            )
            document_query = (
                select(DocumentVersionRow)
                .join(ShipmentDocumentRow, ShipmentDocumentRow.id == DocumentVersionRow.document_id)
                .where(
                    DocumentVersionRow.organization_id == organization_id,
                    DocumentVersionRow.uploaded_at < cutoffs["document_days"],
                    ShipmentDocumentRow.current_version_id != DocumentVersionRow.id,
                )
            )
            if held_ids:
                document_query = document_query.where(
                    ~ShipmentDocumentRow.shipment_id.in_(held_ids)
                )
            document_count = int(len(list(session.scalars(document_query))))
            holds = int(
                session.scalar(
                    select(func.count(LegalHoldRow.id)).where(
                        LegalHoldRow.organization_id == organization_id,
                        LegalHoldRow.active.is_(True),
                    )
                )
                or 0
            )
        return {
            "policy": policy,
            "cutoffs": cutoffs,
            "legal_holds": holds,
            "candidates": {
                "audit_events": audit_count,
                "processing_jobs": job_count,
                "webhook_deliveries": webhook_count,
                "document_bytes": document_count,
            },
            "mutated": False,
        }

    def cleanup_retention(self, *, organization_id: str) -> dict[str, Any]:
        preview = self.retention_dry_run(organization_id=organization_id)
        policy = preview["policy"]
        cutoffs = preview["cutoffs"]
        with self.session_factory() as session:
            held_ids = set(
                session.scalars(
                    select(LegalHoldRow.shipment_id).where(
                        LegalHoldRow.organization_id == organization_id,
                        LegalHoldRow.active.is_(True),
                    )
                )
            )
            audit_query = delete(AuditEventRow).where(
                AuditEventRow.organization_id == organization_id,
                AuditEventRow.created_at < cutoffs["audit_days"],
            )
            if held_ids:
                audit_query = audit_query.where(~AuditEventRow.entity_id.in_(held_ids))
            audit_deleted = int(session.execute(audit_query).rowcount or 0)
            jobs_deleted = int(
                session.execute(
                    delete(ProcessingJobRow).where(
                        ProcessingJobRow.organization_id == organization_id,
                        ProcessingJobRow.queued_at < cutoffs["job_days"],
                        ProcessingJobRow.status.in_(["SUCCEEDED", "FAILED", "DEAD_LETTER"]),
                    )
                ).rowcount
                or 0
            )
            webhook_deleted = int(
                session.execute(
                    delete(WebhookDeliveryRow).where(
                        WebhookDeliveryRow.organization_id == organization_id,
                        WebhookDeliveryRow.created_at < cutoffs["webhook_days"],
                        WebhookDeliveryRow.status.in_(["DELIVERED", "FAILED"]),
                    )
                ).rowcount
                or 0
            )
            document_query = (
                select(DocumentVersionRow)
                .join(ShipmentDocumentRow, ShipmentDocumentRow.id == DocumentVersionRow.document_id)
                .where(
                    DocumentVersionRow.organization_id == organization_id,
                    DocumentVersionRow.uploaded_at < cutoffs["document_days"],
                    ShipmentDocumentRow.current_version_id != DocumentVersionRow.id,
                )
            )
            if held_ids:
                document_query = document_query.where(
                    ~ShipmentDocumentRow.shipment_id.in_(held_ids)
                )
            old_versions = list(session.scalars(document_query))
            from app.services.document_storage import DocumentStorage

            storage = DocumentStorage(get_settings().document_storage_root)
            for version in old_versions:
                storage.path_for(version.storage_key).unlink(missing_ok=True)
                session.delete(version)
            session.commit()
        return {
            "policy": policy,
            "deleted": {
                "audit_events": audit_deleted,
                "processing_jobs": jobs_deleted,
                "webhook_deliveries": webhook_deleted,
                "document_bytes": len(old_versions),
            },
            "mutated": True,
        }

    def set_legal_hold(
        self,
        *,
        organization_id: str,
        shipment_id: str,
        user: UserRow,
        active: bool,
        reason: str,
    ) -> dict[str, Any]:
        now = now_utc()
        reason = " ".join(reason.split())
        if active and len(reason) < 3:
            raise GateGuardError(
                "A legal hold requires a reason.", code="VALIDATION_ERROR", status_code=422
            )
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            hold = session.scalar(
                select(LegalHoldRow).where(
                    LegalHoldRow.organization_id == organization_id,
                    LegalHoldRow.shipment_id == shipment_id,
                )
            )
            if hold is None:
                hold = LegalHoldRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    shipment_id=shipment_id,
                    reason=reason,
                    active=active,
                    created_by=user.id,
                    created_at=now,
                    released_at=None if active else now,
                )
                session.add(hold)
            else:
                hold.reason = reason or hold.reason
                hold.active = active
                hold.released_at = None if active else now
            session.commit()
            return row_dict(hold)

    def create_connection(
        self, *, organization_id: str, user: UserRow, payload: dict[str, Any]
    ) -> dict[str, Any]:
        now = now_utc()
        credential_reference = str(payload.get("credential_reference") or "").strip() or None
        if credential_reference and (
            len(credential_reference) > 160 or any(char.isspace() for char in credential_reference)
        ):
            raise GateGuardError(
                "Credential reference must be a short server-side identifier.",
                code="INVALID_CREDENTIAL_REFERENCE",
                status_code=422,
            )
        safe_configuration = sanitize_connection_configuration(payload.get("configuration", {}))
        row = IntegrationConnectionRow(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=str(payload["name"]).strip(),
            type=str(payload["type"]),
            status="DISABLED",
            configuration_safe_json=json.dumps(safe_configuration, sort_keys=True),
            credential_reference=credential_reference,
            created_at=now,
            updated_at=now,
        )
        with self.session_factory() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return row_dict(row, exclude={"configuration_safe_json", "credential_reference"}) | {
                "configuration": safe_configuration,
                "credential_configured": bool(credential_reference),
            }

    def connection_action(
        self,
        *,
        organization_id: str,
        connection_id: str,
        action: str,
        credential_reference: str | None = None,
    ) -> dict[str, Any]:
        """Run an explicit connection lifecycle action without claiming provider coverage."""
        now = now_utc()
        with self.session_factory() as session:
            row = session.scalar(
                select(IntegrationConnectionRow).where(
                    IntegrationConnectionRow.id == connection_id,
                    IntegrationConnectionRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise NotFoundError("Connection was not found in this workspace.")
            configuration = json.loads(row.configuration_safe_json or "{}")
            if action == "VALIDATE":
                base_url = configuration.get("base_url")
                valid_url = True
                if base_url:
                    try:
                        validate_connection_base_url(
                            str(base_url),
                            production=get_settings().app_env.casefold() == "production",
                        )
                    except GateGuardError:
                        valid_url = False
                return {
                    "id": row.id,
                    "status": row.status,
                    "provider_capability": "NOT_CONFIGURED",
                    "checks": {
                        "metadata": "PASS" if valid_url else "FAIL",
                        "credential_reference": "PASS" if row.credential_reference else "MISSING",
                        "provider_adapter": "NOT_CONFIGURED",
                    },
                    "ready_to_enable": False,
                }
            if action == "TEST":
                row.last_error_at = now
                row.updated_at = now
                session.commit()
                return {
                    "id": row.id,
                    "status": row.status,
                    "provider_status": "NOT_CONFIGURED",
                    "message": (
                        "No provider adapter is configured; the connection remains disabled."
                    ),
                    "last_success_at": row.last_success_at,
                    "last_error_at": row.last_error_at,
                }
            if action == "ENABLE":
                if not row.credential_reference:
                    raise GateGuardError(
                        "A server-side credential reference is required before enabling "
                        "a connection.",
                        code="CREDENTIAL_REFERENCE_REQUIRED",
                        status_code=409,
                    )
                raise GateGuardError(
                    "The provider adapter is not configured; the connection cannot be enabled.",
                    code="PROVIDER_NOT_CONFIGURED",
                    status_code=409,
                )
            if action == "DISABLE":
                row.status = "DISABLED"
            elif action == "ROTATE":
                reference = str(credential_reference or "").strip()
                if (
                    not reference
                    or len(reference) > 160
                    or any(char.isspace() for char in reference)
                ):
                    raise GateGuardError(
                        "Credential rotation requires a server-side reference.",
                        code="INVALID_CREDENTIAL_REFERENCE",
                        status_code=422,
                    )
                row.credential_reference = reference
                row.status = "DISABLED"
                row.last_success_at = None
                row.last_error_at = None
            elif action == "DELETE":
                row.status = "DELETED"
            else:
                raise GateGuardError(
                    "Unsupported connection action.", code="VALIDATION_ERROR", status_code=422
                )
            row.updated_at = now
            session.commit()
            return row_dict(row, exclude={"configuration_safe_json", "credential_reference"}) | {
                "configuration": configuration,
                "credential_configured": bool(row.credential_reference),
            }

    def create_webhook(self, *, organization_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        secret = secrets.token_urlsafe(32)
        now = now_utc()
        events = normalize_webhook_events(payload.get("events", []))
        endpoint = validate_webhook_endpoint(
            str(payload["endpoint"]), production=get_settings().app_env.casefold() == "production"
        )
        row = WebhookSubscriptionRow(
            id=str(uuid.uuid4()),
            organization_id=organization_id,
            name=str(payload["name"]).strip(),
            endpoint=endpoint,
            events_json=json.dumps(events),
            secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
            secret_ciphertext=encrypt_secret(secret, get_settings()),
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        with self.session_factory() as session:
            session.add(row)
            session.commit()
        return {
            "subscription": row_dict(row, exclude={"secret_ciphertext", "secret_hash"})
            | {
                "events": events,
                "secret_configured": True,
                "secret_reveal": "one_time_on_create",
                "delivery_capability": "QUEUED_DELIVERY",
            },
            "secret": secret,
        }

    def queue_webhook_delivery(
        self,
        *,
        organization_id: str,
        subscription_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
        allow_unlisted_test: bool = False,
    ) -> dict[str, Any]:
        now = now_utc()
        event_names = normalize_webhook_events([event_type])
        if not event_names:
            raise GateGuardError(
                "Event type is required.", code="VALIDATION_ERROR", status_code=422
            )
        event_name = event_names[0]
        with self.session_factory() as session:
            subscription = session.scalar(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.organization_id == organization_id,
                )
            )
            if subscription is None:
                raise NotFoundError("Webhook subscription was not found in this workspace.")
            if not subscription.enabled:
                raise GateGuardError(
                    "Webhook subscription is disabled.", code="WEBHOOK_DISABLED", status_code=409
                )
            events = json.loads(subscription.events_json or "[]")
            if events and event_name not in events and not allow_unlisted_test:
                raise GateGuardError(
                    "This event is not enabled for the webhook.",
                    code="WEBHOOK_EVENT_DISABLED",
                    status_code=422,
                )
            delivery = WebhookDeliveryRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                subscription_id=subscription_id,
                event_type=event_name,
                event_id=event_id,
                payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                status="QUEUED",
                attempts=0,
                last_error=None,
                next_attempt_at=None,
                created_at=now,
            )
            job = ProcessingJobRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=None,
                job_type=ProcessingJobType.SEND_WEBHOOK.value,
                status="QUEUED",
                attempts=0,
                max_attempts=4,
                priority=40,
                payload_json=json.dumps({"delivery_id": delivery.id}),
                queued_at=now,
            )
            session.add_all([delivery, job])
            session.commit()
            return {"delivery": row_dict(delivery, exclude={"payload_json"}), "job_id": job.id}

    def enqueue_domain_event_deliveries(self, *, limit: int = 200) -> int:
        """Project committed domain events into the webhook outbox idempotently."""
        now = now_utc()
        created = 0
        with self.session_factory() as session:
            subscriptions = list(
                session.scalars(
                    select(WebhookSubscriptionRow).where(WebhookSubscriptionRow.enabled.is_(True))
                )
            )
            if not subscriptions:
                return 0
            events = list(
                session.scalars(
                    select(DomainEventRow)
                    .order_by(DomainEventRow.created_at.desc())
                    .limit(max(1, min(limit, 500)))
                )
            )
            for event in events:
                for subscription in subscriptions:
                    if subscription.organization_id != event.organization_id:
                        continue
                    allowed = json.loads(subscription.events_json or "[]")
                    if allowed and event.event_type not in allowed:
                        continue
                    duplicate = session.scalar(
                        select(WebhookDeliveryRow.id).where(
                            WebhookDeliveryRow.subscription_id == subscription.id,
                            WebhookDeliveryRow.event_id == event.id,
                        )
                    )
                    if duplicate:
                        continue
                    delivery = WebhookDeliveryRow(
                        id=str(uuid.uuid4()),
                        organization_id=event.organization_id,
                        subscription_id=subscription.id,
                        event_type=event.event_type,
                        event_id=event.id,
                        payload_json=json.dumps(
                            {
                                "event_id": event.id,
                                "event_type": event.event_type,
                                "entity_type": event.entity_type,
                                "entity_id": event.entity_id,
                                "data": json.loads(event.payload_json or "{}"),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        status="QUEUED",
                        attempts=0,
                        created_at=now,
                    )
                    job = ProcessingJobRow(
                        id=str(uuid.uuid4()),
                        organization_id=event.organization_id,
                        shipment_id=event.entity_id if event.entity_type == "shipment" else None,
                        job_type=ProcessingJobType.SEND_WEBHOOK.value,
                        status="QUEUED",
                        attempts=0,
                        max_attempts=4,
                        priority=40,
                        payload_json=json.dumps({"delivery_id": delivery.id}),
                        queued_at=now,
                    )
                    session.add_all([delivery, job])
                    created += 1
            session.commit()
        return created

    def list_webhook_deliveries(
        self, *, organization_id: str, subscription_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(WebhookDeliveryRow)
                .where(
                    WebhookDeliveryRow.organization_id == organization_id,
                    WebhookDeliveryRow.subscription_id == subscription_id,
                )
                .order_by(WebhookDeliveryRow.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
            return [row_dict(row, exclude={"payload_json"}) for row in rows]

    def webhook_delivery_context(self, *, organization_id: str, delivery_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            row = session.scalar(
                select(WebhookDeliveryRow).where(
                    WebhookDeliveryRow.id == delivery_id,
                    WebhookDeliveryRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise NotFoundError("Webhook delivery was not found in this workspace.")
            subscription = session.scalar(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == row.subscription_id,
                    WebhookSubscriptionRow.organization_id == organization_id,
                )
            )
            if subscription is None:
                raise NotFoundError("Webhook delivery was not found in this workspace.")
            if not subscription.enabled:
                raise GateGuardError(
                    "Webhook subscription is disabled.", code="WEBHOOK_DISABLED", status_code=409
                )
            if not subscription.secret_ciphertext:
                raise GateGuardError(
                    "Webhook signing secret is unavailable.",
                    code="WEBHOOK_SECRET_UNAVAILABLE",
                    status_code=503,
                )
            return {
                "delivery": row_dict(row),
                "subscription": row_dict(
                    subscription, exclude={"secret_hash", "secret_ciphertext"}
                ),
                "secret": decrypt_secret(subscription.secret_ciphertext, get_settings()),
            }

    def finish_webhook_delivery(
        self,
        *,
        delivery_id: str,
        success: bool,
        response_code: int | None = None,
        safe_error: str | None = None,
    ) -> None:
        now = now_utc()
        with self.session_factory() as session:
            row = session.get(WebhookDeliveryRow, delivery_id)
            if row is None:
                return
            row.response_code = response_code
            row.last_error = safe_error
            row.delivered_at = now if success else None
            row.status = "DELIVERED" if success else "FAILED"
            row.next_attempt_at = None
            session.commit()

    def mark_webhook_delivery_retry(self, *, delivery_id: str, safe_error: str) -> None:
        now = now_utc()
        with self.session_factory() as session:
            row = session.get(WebhookDeliveryRow, delivery_id)
            if row is None:
                return
            row.attempts += 1
            row.status = "RETRYING"
            row.last_error = safe_error[:240]
            row.next_attempt_at = now + timedelta(seconds=min(300, 2 ** max(row.attempts, 1) * 5))
            session.commit()

    def retry_webhook_delivery(self, *, organization_id: str, delivery_id: str) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            delivery = session.scalar(
                select(WebhookDeliveryRow).where(
                    WebhookDeliveryRow.id == delivery_id,
                    WebhookDeliveryRow.organization_id == organization_id,
                )
            )
            if delivery is None:
                raise NotFoundError("Webhook delivery was not found in this workspace.")
            subscription = session.scalar(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == delivery.subscription_id,
                    WebhookSubscriptionRow.organization_id == organization_id,
                )
            )
            if subscription is None or not subscription.enabled:
                raise GateGuardError(
                    "Webhook subscription is disabled.", code="WEBHOOK_DISABLED", status_code=409
                )
            delivery.status = "QUEUED"
            delivery.next_attempt_at = None
            delivery.last_error = None
            job = ProcessingJobRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=None,
                job_type=ProcessingJobType.SEND_WEBHOOK.value,
                status="QUEUED",
                attempts=0,
                max_attempts=4,
                priority=40,
                payload_json=json.dumps({"delivery_id": delivery.id, "manual_retry": True}),
                queued_at=now,
            )
            session.add(job)
            session.commit()
            return {"delivery": row_dict(delivery, exclude={"payload_json"}), "job_id": job.id}

    def webhook_action(
        self,
        *,
        organization_id: str,
        subscription_id: str,
        action: str,
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            subscription = session.scalar(
                select(WebhookSubscriptionRow).where(
                    WebhookSubscriptionRow.id == subscription_id,
                    WebhookSubscriptionRow.organization_id == organization_id,
                )
            )
            if subscription is None:
                raise NotFoundError("Webhook subscription was not found in this workspace.")
            secret: str | None = None
            if action == "ROTATE":
                secret = secrets.token_urlsafe(32)
                subscription.secret_hash = hashlib.sha256(secret.encode()).hexdigest()
                subscription.secret_ciphertext = encrypt_secret(secret, get_settings())
            elif action == "ENABLE":
                subscription.enabled = True
            elif action == "DISABLE" or action == "DELETE":
                subscription.enabled = False
            else:
                raise GateGuardError(
                    "Unsupported webhook action.", code="VALIDATION_ERROR", status_code=422
                )
            subscription.updated_at = now
            session.commit()
            result = {
                **row_dict(subscription, exclude={"secret_hash", "secret_ciphertext"}),
                "events": json.loads(subscription.events_json or "[]"),
                "secret_configured": bool(subscription.secret_hash),
            }
            if secret:
                result["secret"] = secret
            return result

    def escalate_overdue_tasks(self, *, organization_id: str) -> int:
        """Create idempotent supervisor notifications for overdue review tasks."""
        now = now_utc()
        created = 0
        with self.session_factory() as session:
            overdue = list(
                session.scalars(
                    select(ReviewTaskRow)
                    .where(
                        ReviewTaskRow.organization_id == organization_id,
                        ReviewTaskRow.status.not_in(["RESOLVED", "CANCELLED"]),
                        ReviewTaskRow.due_at.is_not(None),
                        ReviewTaskRow.due_at < now,
                    )
                    .limit(200)
                )
            )
            recipients = list(
                session.scalars(
                    select(UserRow)
                    .join(WorkspaceMembershipRow, WorkspaceMembershipRow.user_id == UserRow.id)
                    .where(
                        WorkspaceMembershipRow.organization_id == organization_id,
                        WorkspaceMembershipRow.active.is_(True),
                        UserRow.active.is_(True),
                        UserRow.role.in_(["supervisor", "admin"]),
                    )
                )
            )
            for task in overdue:
                for recipient in recipients:
                    exists = session.scalar(
                        select(NotificationRow.id).where(
                            NotificationRow.organization_id == organization_id,
                            NotificationRow.user_id == recipient.id,
                            NotificationRow.event_type == "review_task.overdue",
                            NotificationRow.href == f"/work-queue?task={task.id}",
                            NotificationRow.created_at >= now - timedelta(hours=24),
                        )
                    )
                    if exists:
                        continue
                    session.add(
                        NotificationRow(
                            id=str(uuid.uuid4()),
                            organization_id=organization_id,
                            user_id=recipient.id,
                            event_type="review_task.overdue",
                            title="Overdue review task",
                            body="A shipment review task is past its due time.",
                            href=f"/work-queue?task={task.id}",
                            read_at=None,
                            created_at=now,
                        )
                    )
                    created += 1
            session.commit()
        return created

    def create_service_token(
        self, *, organization_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raw = f"gg_{secrets.token_urlsafe(32)}"
        now = now_utc()
        scopes = normalize_service_scopes(payload.get("scopes", ["shipment.read"]))
        expires_at = normalize_service_expiry(payload.get("expires_at"), now=now)
        with self.session_factory() as session:
            account = ServiceAccountRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                name=str(payload["name"]).strip(),
                active=True,
                created_at=now,
            )
            session.add(account)
            session.flush()
            token = ApiTokenRow(
                id=str(uuid.uuid4()),
                service_account_id=account.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                prefix=raw[:10],
                scopes=json.dumps(scopes),
                expires_at=expires_at,
                revoked_at=None,
                last_used_at=None,
                created_at=now,
            )
            session.add(token)
            session.commit()
            return {
                "service_account": row_dict(account),
                "token": raw,
                "token_prefix": token.prefix,
                "expires_at": token.expires_at,
                "scopes": scopes,
            }

    def list_service_accounts(self, *, organization_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as session:
            accounts = list(
                session.scalars(
                    select(ServiceAccountRow)
                    .where(ServiceAccountRow.organization_id == organization_id)
                    .order_by(ServiceAccountRow.created_at.desc())
                )
            )
            output: list[dict[str, Any]] = []
            for account in accounts:
                tokens = list(
                    session.scalars(
                        select(ApiTokenRow)
                        .where(ApiTokenRow.service_account_id == account.id)
                        .order_by(ApiTokenRow.created_at.desc())
                    )
                )
                output.append(
                    {
                        **row_dict(account),
                        "tokens": [
                            {
                                "id": token.id,
                                "prefix": token.prefix,
                                "scopes": json.loads(token.scopes or "[]"),
                                "expires_at": token.expires_at,
                                "revoked_at": token.revoked_at,
                                "last_used_at": token.last_used_at,
                                "created_at": token.created_at,
                            }
                            for token in tokens
                        ],
                    }
                )
            return output

    def revoke_service_account(
        self, *, organization_id: str, service_account_id: str
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            account = session.scalar(
                select(ServiceAccountRow).where(
                    ServiceAccountRow.id == service_account_id,
                    ServiceAccountRow.organization_id == organization_id,
                )
            )
            if account is None:
                raise NotFoundError("Service account was not found in this workspace.")
            account.active = False
            for token in session.scalars(
                select(ApiTokenRow).where(ApiTokenRow.service_account_id == account.id)
            ):
                token.revoked_at = token.revoked_at or now
            session.commit()
            return row_dict(account)

    def rotate_service_token(
        self, *, organization_id: str, service_account_id: str, expires_at: datetime | None = None
    ) -> dict[str, Any]:
        now = now_utc()
        expires_at = normalize_service_expiry(expires_at, now=now)
        raw = f"gg_{secrets.token_urlsafe(32)}"
        with self.session_factory() as session:
            account = session.scalar(
                select(ServiceAccountRow).where(
                    ServiceAccountRow.id == service_account_id,
                    ServiceAccountRow.organization_id == organization_id,
                    ServiceAccountRow.active.is_(True),
                )
            )
            if account is None:
                raise NotFoundError("Active service account was not found in this workspace.")
            previous = list(
                session.scalars(
                    select(ApiTokenRow).where(
                        ApiTokenRow.service_account_id == account.id,
                        ApiTokenRow.revoked_at.is_(None),
                    )
                )
            )
            scopes = (
                normalize_service_scopes(json.loads(previous[0].scopes or "[]"))
                if previous
                else ["shipment.read"]
            )
            for token in previous:
                token.revoked_at = now
            token = ApiTokenRow(
                id=str(uuid.uuid4()),
                service_account_id=account.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                prefix=raw[:10],
                scopes=json.dumps(scopes),
                expires_at=expires_at,
                revoked_at=None,
                last_used_at=None,
                created_at=now,
            )
            session.add(token)
            session.commit()
            return {
                "service_account": row_dict(account),
                "token": raw,
                "token_prefix": token.prefix,
                "expires_at": token.expires_at,
                "scopes": scopes,
            }

    def service_token_context(self, raw_token: str) -> ServicePrincipal:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = now_utc()
        with self.session_factory() as session:
            row = session.execute(
                select(ApiTokenRow, ServiceAccountRow)
                .join(ServiceAccountRow, ServiceAccountRow.id == ApiTokenRow.service_account_id)
                .where(
                    ApiTokenRow.token_hash == token_hash,
                    ApiTokenRow.revoked_at.is_(None),
                    ServiceAccountRow.active.is_(True),
                )
            ).first()
            if row is None or (row[0].expires_at and row[0].expires_at <= now):
                raise GateGuardError(
                    "API token is invalid or expired.", code="INVALID_TOKEN", status_code=401
                )
            token, account = row
            token.last_used_at = now
            session.commit()
            return ServicePrincipal(
                service_account_id=account.id,
                organization_id=account.organization_id,
                display_name=account.name,
                scopes=frozenset(json.loads(token.scopes or "[]")),
            )

    def record_reconciliation_check(
        self,
        *,
        organization_id: str,
        shipment_id: str | None,
        user: UserRow,
        result: Any,
    ) -> dict[str, Any] | None:
        """Bring the original document-check flow into the assurance ledger."""
        if not shipment_id:
            return None
        now = now_utc()
        status = result.status.value if hasattr(result.status, "value") else str(result.status)
        severity = "LOW" if status == "CLEAR" else "HIGH" if status == "HOLD" else "MEDIUM"
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                return None
            check = AssuranceCheckRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                check_type="DOCUMENT_RECONCILIATION",
                status=status,
                severity=severity,
                summary=result.reason,
                details_json=json.dumps(
                    {
                        "session_id": result.session_id,
                        "mismatches": [item.model_dump(mode="json") for item in result.mismatches],
                        "recommended_action": result.recommended_action,
                    }
                ),
                source="GateGuard document assurance",
                source_version="1",
                started_at=result.created_at,
                completed_at=now,
                created_at=now,
            )
            shipment.last_assessed_at = now
            shipment.updated_at = now
            if status in {"REVIEW", "HOLD"}:
                shipment.status = (
                    ShipmentStatus.HOLD.value
                    if status == "HOLD"
                    else ShipmentStatus.REVIEW_REQUIRED.value
                )
            session.add(check)
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="assurance.check.completed",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    payload_json=json.dumps({"check_type": check.check_type, "status": status}),
                    created_at=now,
                )
            )
            session.commit()
            return row_dict(check) | {"details": json.loads(check.details_json)}

    def update_exception(
        self,
        *,
        organization_id: str,
        exception_id: str,
        user: UserRow,
        status: str | None = None,
        assigned_to: str | None = None,
        resolution_code: str | None = None,
        resolution_note: str | None = None,
    ) -> dict[str, Any]:
        now = now_utc()
        allowed_statuses = {"OPEN", "IN_PROGRESS", "RESOLVED", "CANCELLED"}
        if status and status not in allowed_statuses:
            raise GateGuardError(
                "Invalid exception status.", code="VALIDATION_ERROR", status_code=422
            )
        with self.session_factory() as session:
            row = session.scalar(
                select(ShipmentExceptionRow).where(
                    ShipmentExceptionRow.id == exception_id,
                    ShipmentExceptionRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise NotFoundError("Exception was not found in this workspace.")
            if status:
                row.status = status
            if assigned_to is not None:
                assignee = (
                    session.scalar(
                        select(UserRow)
                        .join(WorkspaceMembershipRow, WorkspaceMembershipRow.user_id == UserRow.id)
                        .where(
                            UserRow.id == assigned_to,
                            UserRow.active.is_(True),
                            WorkspaceMembershipRow.organization_id == organization_id,
                            WorkspaceMembershipRow.active.is_(True),
                        )
                    )
                    if assigned_to
                    else None
                )
                if assigned_to and assignee is None:
                    raise NotFoundError("Assigned person was not found.")
                row.assigned_to = assigned_to or None
            if resolution_code is not None:
                row.resolution_code = resolution_code.strip() or None
            if resolution_note is not None:
                row.resolution_note = resolution_note.strip() or None
            if row.status == "RESOLVED":
                row.resolved_at = now
                row.resolved_by = user.id
            row.updated_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="exception.updated",
                    entity_type="exception",
                    entity_id=exception_id,
                    payload_json=json.dumps({"status": row.status}),
                    created_at=now,
                )
            )
            session.commit()
            return row_dict(row)

    def add_exception_comment(
        self, *, organization_id: str, exception_id: str, user: UserRow, body: str
    ) -> dict[str, Any]:
        text = " ".join(body.split())
        if len(text) < 2:
            raise GateGuardError(
                "Comment cannot be empty.", code="VALIDATION_ERROR", status_code=422
            )
        with self.session_factory() as session:
            exists = session.scalar(
                select(ShipmentExceptionRow.id).where(
                    ShipmentExceptionRow.id == exception_id,
                    ShipmentExceptionRow.organization_id == organization_id,
                )
            )
            if exists is None:
                raise NotFoundError("Exception was not found in this workspace.")
            row = ExceptionCommentRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                exception_id=exception_id,
                author_id=user.id,
                body=text,
                created_at=now_utc(),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row_dict(row) | {"author_name": user.display_name}

    def create_document_metadata(
        self, *, organization_id: str, user: UserRow, payload: dict[str, Any]
    ) -> dict[str, Any]:
        now = now_utc()
        document_type = str(payload["document_type"]).upper()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == payload["shipment_id"],
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            document = ShipmentDocumentRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment.id,
                document_type=document_type,
                requirement_id=payload.get("requirement_id"),
                current_version_id=None,
                status="UPLOADED",
                created_at=now,
                updated_at=now,
            )
            version = DocumentVersionRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                document_id=document.id,
                version=1,
                filename=str(payload["filename"]).strip(),
                mime_type=str(payload.get("mime_type") or "application/octet-stream"),
                size_bytes=int(payload.get("size_bytes") or 0),
                sha256=str(payload.get("sha256") or ""),
                uploaded_by=user.id,
                uploaded_at=now,
                storage_key=f"{organization_id}/{shipment.id}/{document.id}/1",
                extraction_status="QUEUED",
                extraction_provider=None,
                extraction_confidence=None,
                supersedes_version_id=None,
            )
            document.current_version_id = version.id
            session.add_all([document, version])
            evaluations = list(
                session.scalars(
                    select(RequirementEvaluationRow)
                    .join(
                        DocumentRequirementRow,
                        DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                    )
                    .where(
                        RequirementEvaluationRow.shipment_id == shipment.id,
                        DocumentRequirementRow.document_type == document_type,
                    )
                )
            )
            for evaluation in evaluations:
                evaluation.result = "PROVIDED"
                evaluation.reason = "Evidence is attached; content checks are pending."
                evaluation.evaluated_at = now
            session.add(
                ProcessingJobRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    shipment_id=shipment.id,
                    job_type=ProcessingJobType.EXTRACT_DOCUMENT.value,
                    status="QUEUED",
                    attempts=0,
                    max_attempts=3,
                    priority=50,
                    payload_json=json.dumps({"document_id": document.id, "version_id": version.id}),
                    queued_at=now,
                )
            )
            shipment.updated_at = now
            session.commit()
            session.refresh(document)
            return row_dict(document) | {"version": row_dict(version, exclude={"storage_key"})}

    def create_document_version(
        self,
        *,
        organization_id: str,
        user: UserRow,
        shipment_id: str,
        document_type: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
        document_id: str | None = None,
        requirement_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist an uploaded document version without exposing its storage path."""
        now = now_utc()
        normalized_type = document_type.upper()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            document = (
                session.scalar(
                    select(ShipmentDocumentRow).where(
                        ShipmentDocumentRow.id == document_id,
                        ShipmentDocumentRow.organization_id == organization_id,
                        ShipmentDocumentRow.shipment_id == shipment_id,
                    )
                )
                if document_id
                else None
            )
            if document is None:
                document = ShipmentDocumentRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    shipment_id=shipment_id,
                    document_type=normalized_type,
                    requirement_id=requirement_id,
                    current_version_id=None,
                    status="RECEIVED",
                    created_at=now,
                    updated_at=now,
                )
                session.add(document)
                session.flush()
            versions = list(
                session.scalars(
                    select(DocumentVersionRow)
                    .where(DocumentVersionRow.document_id == document.id)
                    .order_by(DocumentVersionRow.version.desc())
                )
            )
            previous = versions[0] if versions else None
            version = DocumentVersionRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                document_id=document.id,
                version=(previous.version + 1) if previous else 1,
                filename=filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256,
                uploaded_by=user.id,
                uploaded_at=now,
                storage_key=storage_key,
                extraction_status="QUEUED",
                extraction_provider=None,
                extraction_confidence=None,
                supersedes_version_id=previous.id if previous else None,
            )
            if previous:
                previous_document = document
                previous_document.status = "SUPERSEDED"
            document.current_version_id = version.id
            document.status = "RECEIVED"
            document.updated_at = now
            session.add(version)
            evaluations = list(
                session.scalars(
                    select(RequirementEvaluationRow)
                    .join(
                        DocumentRequirementRow,
                        DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                    )
                    .where(
                        RequirementEvaluationRow.shipment_id == shipment_id,
                        DocumentRequirementRow.document_type.in_({normalized_type, "INVOICE"})
                        if normalized_type == "COMMERCIAL_INVOICE"
                        else DocumentRequirementRow.document_type == normalized_type,
                    )
                )
            )
            for evaluation in evaluations:
                evaluation.result = "PROVIDED"
                evaluation.reason = "Evidence was uploaded; content checks are queued."
                evaluation.evaluated_at = now
            session.add(
                ProcessingJobRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    shipment_id=shipment_id,
                    job_type=ProcessingJobType.EXTRACT_DOCUMENT.value,
                    status="QUEUED",
                    attempts=0,
                    max_attempts=3,
                    priority=60,
                    payload_json=json.dumps({"document_id": document.id, "version_id": version.id}),
                    queued_at=now,
                    next_attempt_at=None,
                )
            )
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="document.uploaded",
                    entity_type="document",
                    entity_id=document.id,
                    payload_json=json.dumps({"version": version.version, "sha256": sha256}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(document)
            session.refresh(version)
            return row_dict(document) | {"version": row_dict(version, exclude={"storage_key"})}

    def document_content_metadata(
        self, *, organization_id: str, document_id: str, version: int | None = None
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            document = session.scalar(
                select(ShipmentDocumentRow).where(
                    ShipmentDocumentRow.id == document_id,
                    ShipmentDocumentRow.organization_id == organization_id,
                )
            )
            if document is None:
                raise NotFoundError("Document was not found in this workspace.")
            stmt = select(DocumentVersionRow).where(
                DocumentVersionRow.document_id == document.id,
                DocumentVersionRow.organization_id == organization_id,
            )
            if version is not None:
                stmt = stmt.where(DocumentVersionRow.version == version)
            else:
                stmt = stmt.where(DocumentVersionRow.id == document.current_version_id)
            current = session.scalar(stmt)
            if current is None:
                raise NotFoundError("Document version was not found.")
            return row_dict(current) | {"document": row_dict(document)}

    def document_extraction_context(
        self, *, organization_id: str, document_id: str, version_id: str
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            document = session.scalar(
                select(ShipmentDocumentRow).where(
                    ShipmentDocumentRow.id == document_id,
                    ShipmentDocumentRow.organization_id == organization_id,
                )
            )
            version = session.scalar(
                select(DocumentVersionRow).where(
                    DocumentVersionRow.id == version_id,
                    DocumentVersionRow.organization_id == organization_id,
                    DocumentVersionRow.document_id == document_id,
                )
            )
            if document is None or version is None:
                raise NotFoundError("The document version was not found in this workspace.")
            return row_dict(document) | {"version": row_dict(version)}

    def complete_document_extraction(
        self,
        *,
        organization_id: str,
        document_id: str,
        version_id: str,
        result: Any,
    ) -> None:
        """Persist an extractor result; output informs review, never a release decision."""
        now = now_utc()
        with self.session_factory() as session:
            document = session.scalar(
                select(ShipmentDocumentRow).where(
                    ShipmentDocumentRow.id == document_id,
                    ShipmentDocumentRow.organization_id == organization_id,
                )
            )
            version = session.scalar(
                select(DocumentVersionRow).where(
                    DocumentVersionRow.id == version_id,
                    DocumentVersionRow.organization_id == organization_id,
                    DocumentVersionRow.document_id == document_id,
                )
            )
            if document is None or version is None:
                raise NotFoundError("The document version was not found in this workspace.")
            fields = [
                result.document_id,
                result.shipment_id,
                result.sender,
                result.recipient,
                result.destination,
                result.document_total,
            ]
            confidences = [field.confidence for field in fields if field.value is not None]
            confidence = min(confidences) if confidences else 0.0
            review_required = (
                not result.line_items_complete
                or confidence < 0.8
                or result.detected_document_type is None
            )
            version.extraction_status = "NEEDS_REVIEW" if review_required else "EXTRACTED"
            version.extraction_provider = result.extraction_provider
            version.extraction_confidence = confidence
            version.extraction_result_json = result.model_dump_json()
            document.document_reference = (
                str(result.document_id.value) if result.document_id.value is not None else None
            )
            document.status = "REVIEW_REQUIRED" if review_required else "EXTRACTED"
            document.updated_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="document.extraction.completed",
                    entity_type="document",
                    entity_id=document_id,
                    payload_json=json.dumps(
                        {
                            "version_id": version_id,
                            "provider": result.extraction_provider,
                            "confidence": confidence,
                            "review_required": review_required,
                        }
                    ),
                    created_at=now,
                )
            )
            session.commit()

    def save_trusted_reference(
        self, *, organization_id: str, shipment_id: str, user: UserRow, payload: dict[str, Any]
    ) -> dict[str, Any]:
        now = now_utc()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(canonical.encode()).hexdigest()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            policy = self._published_policy(session, organization_id=organization_id, now=now)
            from app.repositories.reconciliations import (
                TrustedReferenceItemRow,
                TrustedShipmentReferenceRow,
            )

            reference = session.scalar(
                select(TrustedShipmentReferenceRow).where(
                    TrustedShipmentReferenceRow.shipment_id == shipment_id,
                    TrustedShipmentReferenceRow.organization_id == organization_id,
                )
            )
            if reference is None:
                reference = TrustedShipmentReferenceRow(
                    id=str(uuid.uuid4()),
                    shipment_id=shipment_id,
                    organization_id=organization_id,
                    version=1,
                    source_type="MANUAL_AUTHORITATIVE_ENTRY",
                    source_system="Workspace entry",
                    retrieved_at=now,
                )
                session.add(reference)
                session.flush()
            else:
                reference.version = (reference.version or 1) + 1
                reference.retrieved_at = now
            reference.order_reference = payload.get("order_reference")
            reference.shipment_reference = (
                payload.get("shipment_reference") or shipment.internal_reference
            )
            reference.expected_shipper = payload.get("expected_shipper")
            reference.expected_recipient = payload.get("expected_recipient")
            reference.expected_destination = (
                payload.get("expected_destination") or shipment.destination
            )
            reference.expected_currency = payload.get("expected_currency")
            reference.expected_total = payload.get("expected_total")
            reference.source_system = str(payload.get("source_system") or "Workspace entry")
            reference.source_type = str(payload.get("source_type") or "MANUAL_AUTHORITATIVE_ENTRY")
            reference.source_record_id = payload.get("source_record_id")
            reference.content_hash = content_hash
            session.query(TrustedReferenceItemRow).filter(
                TrustedReferenceItemRow.reference_id == reference.id
            ).delete(synchronize_session=False)
            for item in payload.get("items", []):
                session.add(
                    TrustedReferenceItemRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        reference_id=reference.id,
                        sku=item.get("sku"),
                        description=item.get("description"),
                        quantity=item.get("quantity"),
                        unit=item.get("unit"),
                        unit_price=item.get("unit_price"),
                        line_total=item.get("line_total"),
                    )
                )
            comparison = self._trusted_comparison(
                session, shipment, reference, payload.get("items", [])
            )
            check = AssuranceCheckRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                check_type="TRUSTED_REFERENCE",
                status="HOLD" if comparison["findings"] else "CLEAR",
                severity="HIGH" if comparison["findings"] else "LOW",
                summary=(
                    "Trusted source conflicts require review."
                    if comparison["findings"]
                    else "Trusted source matches the shipment reference."
                ),
                details_json=json.dumps(comparison),
                source="MANUAL_AUTHORITATIVE_ENTRY",
                source_version=str(reference.version),
                rule_pack_version=policy.version if policy else None,
                started_at=now,
                completed_at=now,
                created_at=now,
            )
            session.add(check)
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="trusted_reference.updated",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    payload_json=json.dumps(
                        {"version": reference.version, "content_hash": content_hash}
                    ),
                    created_at=now,
                )
            )
            stale_release = session.scalar(
                select(ReleaseDecisionRow)
                .where(
                    ReleaseDecisionRow.shipment_id == shipment_id,
                    ReleaseDecisionRow.decision == "AUTHORIZE",
                    ReleaseDecisionRow.invalidated_at.is_(None),
                )
                .order_by(ReleaseDecisionRow.created_at.desc())
            )
            if stale_release is not None:
                stale_release.invalidated_at = now
                if shipment.status in {
                    ShipmentStatus.RELEASE_PENDING_APPROVAL.value,
                    ShipmentStatus.RELEASE_AUTHORIZED.value,
                }:
                    shipment.status = ShipmentStatus.RELEASE_INVALIDATED.value
                    shipment.release_authorized_at = None
                session.add(
                    DomainEventRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        event_type="release.invalidated",
                        entity_type="shipment",
                        entity_id=shipment_id,
                        payload_json=json.dumps({"reason": "trusted_reference_changed"}),
                        created_at=now,
                    )
                )
            session.commit()
            return {
                "reference": row_dict(reference),
                "comparison": comparison,
                "check": row_dict(check),
            }

    @staticmethod
    def _trusted_comparison(
        session: Session, shipment: ShipmentCaseRow, reference: Any, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        if reference.shipment_reference and reference.shipment_reference not in {
            shipment.internal_reference,
            shipment.external_reference,
        }:
            findings.append(
                {"code": "TRUSTED_SHIPMENT_REFERENCE_MISMATCH", "field": "shipment_reference"}
            )
        if (
            reference.expected_destination
            and reference.expected_destination.casefold() != shipment.destination.casefold()
        ):
            findings.append({"code": "TRUSTED_DESTINATION_MISMATCH", "field": "destination"})
        if (
            reference.expected_currency
            and shipment.currency
            and reference.expected_currency.upper() != shipment.currency.upper()
        ):
            findings.append({"code": "TRUSTED_CURRENCY_MISMATCH", "field": "currency"})
        if reference.expected_total is not None:
            # A trusted total is compared only to the authoritative record supplied here;
            # no fuzzy match is used to authorize release.
            expected = float(reference.expected_total)
            if expected < 0:
                findings.append({"code": "TRUSTED_TOTAL_INVALID", "field": "total"})
        if items:
            supplied = {
                str(item.get("sku")): float(item.get("quantity") or 0)
                for item in items
                if item.get("sku")
            }
            if not supplied:
                findings.append({"code": "TRUSTED_SKU_MISSING", "field": "items"})
        return {"findings": findings, "matched": not findings, "source_type": reference.source_type}

    def run_assessment(
        self, *, organization_id: str, shipment_id: str, user: UserRow
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            existing = session.scalar(
                select(ProcessingJobRow)
                .where(
                    ProcessingJobRow.organization_id == organization_id,
                    ProcessingJobRow.shipment_id == shipment_id,
                    ProcessingJobRow.job_type == ProcessingJobType.ASSESS_SHIPMENT.value,
                    ProcessingJobRow.status.in_(["QUEUED", "RUNNING"]),
                )
                .order_by(ProcessingJobRow.queued_at.desc())
            )
            if existing is not None:
                return {
                    "job_id": existing.id,
                    "shipment_id": shipment_id,
                    "status": existing.status,
                }
            shipment.assessment_started_at = now
            shipment.status = ShipmentStatus.ASSESSING.value
            shipment.updated_at = now
            job = ProcessingJobRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                job_type=ProcessingJobType.ASSESS_SHIPMENT.value,
                status="QUEUED",
                attempts=0,
                max_attempts=3,
                priority=80,
                payload_json=json.dumps({"shipment_id": shipment_id}),
                queued_at=now,
            )
            session.add(job)
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="assessment.started",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    payload_json=json.dumps({"job_id": job.id}),
                    created_at=now,
                )
            )
            session.commit()
            return {"job_id": job.id, "shipment_id": shipment_id, "status": "QUEUED"}

    def complete_assessment(self, *, organization_id: str, shipment_id: str) -> dict[str, Any]:
        """Evaluate persisted deterministic inputs and write the assurance ledger."""
        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            policy = self._published_policy(session, organization_id=organization_id, now=now)
            if policy is None:
                session.add(
                    AssuranceCheckRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        shipment_id=shipment_id,
                        check_type="POLICY_CONFIGURATION",
                        status="REVIEW",
                        severity="HIGH",
                        summary="No published assurance policy is available for this workspace.",
                        details_json=json.dumps({"release_blocking": True}),
                        source="POLICY_CONFIGURATION",
                        source_version="UNAVAILABLE",
                        rule_pack_version=None,
                        started_at=now,
                        completed_at=now,
                        created_at=now,
                    )
                )
                shipment.status = ShipmentStatus.REVIEW_REQUIRED.value
                shipment.last_assessed_at = now
                shipment.updated_at = now
                session.add(
                    DomainEventRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        event_type="assessment.blocked_policy_missing",
                        entity_type="shipment",
                        entity_id=shipment_id,
                        payload_json=json.dumps({"reason": "published_policy_missing"}),
                        created_at=now,
                    )
                )
                session.commit()
                return {
                    "shipment_id": shipment_id,
                    "risk_score": 100,
                    "risk_level": "HIGH",
                    "factors": [
                        {"code": "POLICY_CONFIGURATION", "detail": "Published policy unavailable"}
                    ],
                }
            policy_rules = list(
                session.scalars(
                    select(RuleDefinitionRow).where(
                        RuleDefinitionRow.rule_pack_id == policy.id,
                        RuleDefinitionRow.active.is_(True),
                    )
                )
            )
            risk_policy = policy_risk_config(
                [{"condition_json": row.condition_json} for row in policy_rules]
            )
            evaluations = list(
                session.execute(
                    select(RequirementEvaluationRow, DocumentRequirementRow)
                    .join(
                        DocumentRequirementRow,
                        DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                    )
                    .where(RequirementEvaluationRow.shipment_id == shipment_id)
                )
            )
            missing = [
                requirement.name
                for evaluation, requirement in evaluations
                if requirement.status in {"REQUIRED", "ACTIVE"}
                and evaluation.result not in {"PROVIDED", "CLEAR", "NOT_APPLICABLE"}
            ]
            if missing:
                session.add(
                    AssuranceCheckRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        shipment_id=shipment_id,
                        check_type="DOCUMENT_REQUIREMENTS",
                        status="REVIEW",
                        severity="HIGH",
                        summary="Required documents are missing.",
                        details_json=json.dumps({"missing": missing}),
                        source="PUBLISHED_RULE_PACK",
                        source_version=policy.version,
                        rule_pack_version=policy.version,
                        started_at=now,
                        completed_at=now,
                        created_at=now,
                    )
                )
            else:
                session.add(
                    AssuranceCheckRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        shipment_id=shipment_id,
                        check_type="DOCUMENT_REQUIREMENTS",
                        status="CLEAR",
                        severity="LOW",
                        summary="Required document evidence is present.",
                        details_json="{}",
                        source="PUBLISHED_RULE_PACK",
                        source_version=policy.version,
                        rule_pack_version=policy.version,
                        started_at=now,
                        completed_at=now,
                        created_at=now,
                    )
                )
            dg_items = list(
                session.scalars(
                    select(ShipmentItemRow).where(
                        ShipmentItemRow.shipment_id == shipment_id,
                        ShipmentItemRow.dangerous_goods.is_(True),
                    )
                )
            )
            dg_incomplete = [
                item.description
                for item in dg_items
                if not item.un_number or not item.proper_shipping_name or not item.hazard_class
            ]
            if dg_items:
                session.add(
                    AssuranceCheckRow(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        shipment_id=shipment_id,
                        check_type="DANGEROUS_GOODS",
                        status="HOLD" if dg_incomplete else "REVIEW",
                        severity="HIGH" if dg_incomplete else "MEDIUM",
                        summary=(
                            "Dangerous-goods declarations are incomplete."
                            if dg_incomplete
                            else "Dangerous-goods evidence requires review."
                        ),
                        details_json=json.dumps({"incomplete_items": dg_incomplete}),
                        source="PUBLISHED_RULE_PACK",
                        source_version=policy.version,
                        rule_pack_version=policy.version,
                        started_at=now,
                        completed_at=now,
                        created_at=now,
                    )
                )
            factors: list[tuple[str, str]] = []
            if missing:
                factors.append(("MISSING_REQUIRED_DOCUMENT", ", ".join(missing)))
            if dg_incomplete:
                factors.append(("DANGEROUS_GOODS_INCOMPLETE", ", ".join(dg_incomplete)))
            latest_checks: dict[str, AssuranceCheckRow] = {}
            for check in session.scalars(
                select(AssuranceCheckRow)
                .where(AssuranceCheckRow.shipment_id == shipment_id)
                .order_by(AssuranceCheckRow.created_at.desc())
            ):
                latest_checks.setdefault(check.check_type, check)
            if any(
                check.status in {"HOLD", "REVIEW", "PENDING", "RUNNING", "FAILED"}
                for check in latest_checks.values()
            ):
                factors.append(
                    ("BLOCKING_ASSURANCE", "One or more assurance checks require review.")
                )
            assessment = calculate_risk(factors, risk_policy)
            shipment.risk_score = assessment.score
            shipment.risk_level = assessment.level.value
            shipment.risk_factors_json = json.dumps(assessment.factors)
            shipment.last_assessed_at = now
            shipment.updated_at = now
            shipment.status = (
                ShipmentStatus.HOLD.value if dg_incomplete else ShipmentStatus.REVIEW_REQUIRED.value
            )
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="assessment.completed",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    payload_json=json.dumps(
                        {"risk_level": assessment.level.value, "risk_score": assessment.score}
                    ),
                    created_at=now,
                )
            )
            session.commit()
            return {
                "shipment_id": shipment_id,
                "risk_score": assessment.score,
                "risk_level": assessment.level.value,
                "factors": assessment.factors,
                "policy_version": policy.version,
            }

    def run_screening(
        self, *, organization_id: str, shipment_id: str, party_id: str | None = None, user: UserRow
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            policy = self._published_policy(session, organization_id=organization_id, now=now)
            party = session.scalar(
                select(TradePartyRow)
                .join(ShipmentPartyRow, ShipmentPartyRow.party_id == TradePartyRow.id)
                .where(
                    ShipmentPartyRow.shipment_id == shipment_id,
                    TradePartyRow.organization_id == organization_id,
                    *([TradePartyRow.id == party_id] if party_id else []),
                )
                .order_by(TradePartyRow.legal_name.asc())
            )
            if party is None:
                raise GateGuardError(
                    "Add a shipment party before running screening.",
                    code="PARTY_REQUIRED",
                    status_code=422,
                )
            run = ScreeningRunRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                party_id=party.id,
                provider="NOT_CONFIGURED",
                dataset="NOT_CONFIGURED",
                dataset_version="N/A",
                screened_at=now,
                result="NOT_CONFIGURED",
                score=None,
                matched_name=None,
                matched_identifier=None,
                disposition="NOT_CONFIGURED",
                reviewed_by=None,
                reviewed_at=None,
            )
            check = AssuranceCheckRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                check_type="PARTY_SCREENING",
                status="REVIEW",
                severity="HIGH",
                summary="Screening provider is unavailable; manual disposition is required.",
                details_json=json.dumps(
                    {
                        "party_id": party.id,
                        "result": "NOT_CONFIGURED",
                        "release_blocking": True,
                    }
                ),
                source="PUBLISHED_RULE_PACK" if policy else "POLICY_CONFIGURATION",
                source_version=policy.version if policy else "UNAVAILABLE",
                rule_pack_version=policy.version if policy else None,
                started_at=now,
                completed_at=now,
                created_at=now,
            )
            job = ProcessingJobRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                shipment_id=shipment_id,
                job_type=ProcessingJobType.SCREEN_PARTY.value,
                status="QUEUED",
                attempts=0,
                max_attempts=2,
                priority=55,
                payload_json=json.dumps({"run_id": run.id, "party_id": party.id}),
                queued_at=now,
            )
            session.add_all([run, check, job])
            # This mutation only queues the provider job. Emit a started event
            # here; the completed event is written by the worker after the
            # screening result has been committed so consumers never observe a
            # false success before the effect exists.
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="screening.started",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    idempotency_key=f"screening:{run.id}:started",
                    payload_json=json.dumps({"run_id": run.id, "party_id": party.id}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(run)
            return row_dict(run) | {"party_name": party.legal_name, "job_id": job.id}

    def complete_screening_job(self, *, organization_id: str, payload: dict[str, Any]) -> None:
        """Finalize a screening job without ever treating missing provider data as clear."""
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise GateGuardError(
                "Screening job is missing its run identifier.",
                code="INVALID_JOB_PAYLOAD",
                status_code=422,
            )
        with self.session_factory() as session:
            run = session.scalar(
                select(ScreeningRunRow).where(
                    ScreeningRunRow.id == run_id,
                    ScreeningRunRow.organization_id == organization_id,
                )
            )
            if run is None:
                raise NotFoundError("Screening run was not found in this workspace.")
            if run.result in {"CLEAR", "MATCH", "NO_MATCH"} and run.provider != "NOT_CONFIGURED":
                return
            completed_key = f"screening:{run.id}:completed"
            if session.scalar(
                select(DomainEventRow.id).where(
                    DomainEventRow.organization_id == organization_id,
                    DomainEventRow.idempotency_key == completed_key,
                )
            ):
                return
            run.result = "NOT_CONFIGURED"
            run.disposition = "REQUIRES_REVIEW"
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="screening.completed",
                    entity_type="shipment",
                    entity_id=run.shipment_id,
                    idempotency_key=completed_key,
                    payload_json=json.dumps(
                        {
                            "run_id": run.id,
                            "party_id": run.party_id,
                            "result": run.result,
                            "provider": run.provider,
                        }
                    ),
                    created_at=now_utc(),
                )
            )
            session.commit()

    def adjudicate_screening(
        self,
        *,
        organization_id: str,
        run_id: str,
        user: UserRow,
        disposition: str,
        comment: str,
    ) -> dict[str, Any]:
        """Record a human screening disposition and update the latest assurance check."""
        allowed = {"CLEAR", "MATCH", "FALSE_POSITIVE", "REQUIRES_REVIEW"}
        if disposition not in allowed:
            raise GateGuardError(
                "Screening disposition is invalid.", code="VALIDATION_ERROR", status_code=422
            )
        note = " ".join(comment.split())
        if len(note) < 2:
            raise GateGuardError(
                "Screening adjudication requires a reason.",
                code="VALIDATION_ERROR",
                status_code=422,
            )
        now = now_utc()
        with self.session_factory() as session:
            run = session.scalar(
                select(ScreeningRunRow).where(
                    ScreeningRunRow.id == run_id,
                    ScreeningRunRow.organization_id == organization_id,
                )
            )
            if run is None:
                raise NotFoundError("Screening run was not found in this workspace.")
            if run.result == "NOT_CONFIGURED" and disposition != "REQUIRES_REVIEW":
                raise GateGuardError(
                    "An unavailable screening provider cannot be manually marked clear.",
                    code="SCREENING_PROVIDER_UNAVAILABLE",
                    status_code=409,
                )
            if run.result == "MATCH" and disposition == "CLEAR":
                raise GateGuardError(
                    "A matched screening result must be confirmed or marked false positive.",
                    code="SCREENING_MATCH_REQUIRES_REVIEW",
                    status_code=409,
                )
            if disposition == "FALSE_POSITIVE" and run.result != "MATCH":
                raise GateGuardError(
                    "False positive disposition requires a matched screening result.",
                    code="SCREENING_DISPOSITION_INVALID",
                    status_code=409,
                )
            run.disposition = disposition
            run.reviewed_by = user.id
            run.reviewed_at = now
            check = session.scalar(
                select(AssuranceCheckRow)
                .where(
                    AssuranceCheckRow.organization_id == organization_id,
                    AssuranceCheckRow.shipment_id == run.shipment_id,
                    AssuranceCheckRow.check_type == "PARTY_SCREENING",
                )
                .order_by(AssuranceCheckRow.created_at.desc())
            )
            status = (
                "HOLD"
                if disposition == "MATCH"
                else "CLEAR"
                if disposition in {"CLEAR", "FALSE_POSITIVE"}
                else "REVIEW"
            )
            severity = "HIGH" if status == "HOLD" else "LOW" if status == "CLEAR" else "MEDIUM"
            summary = (
                "Screening match confirmed by a reviewer."
                if disposition == "MATCH"
                else "Screening match was marked false positive by a reviewer."
                if disposition == "FALSE_POSITIVE"
                else "Screening result was cleared by a reviewer."
                if disposition == "CLEAR"
                else "Screening remains in manual review."
            )
            if check is None:
                check = AssuranceCheckRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    shipment_id=run.shipment_id,
                    check_type="PARTY_SCREENING",
                    started_at=run.screened_at,
                    created_at=now,
                )
                session.add(check)
            check.status = status
            check.severity = severity
            check.summary = summary
            check.details_json = json.dumps(
                {
                    "party_id": run.party_id,
                    "result": run.result,
                    "disposition": disposition,
                    "comment": note,
                    "reviewed_by": user.id,
                    "release_blocking": status != "CLEAR",
                }
            )
            check.source = "HUMAN_ADJUDICATION"
            check.source_version = run.dataset_version
            check.completed_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="screening.adjudicated",
                    entity_type="shipment",
                    entity_id=run.shipment_id,
                    payload_json=json.dumps(
                        {
                            "run_id": run.id,
                            "result": run.result,
                            "disposition": disposition,
                        }
                    ),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(run)
            return row_dict(run) | {"comment": note, "assurance_status": status}

    @staticmethod
    def _published_policy(
        session: Session, *, organization_id: str, now: datetime
    ) -> RulePackRow | None:
        active_window = (
            RulePackRow.status == "PUBLISHED",
            or_(RulePackRow.effective_from.is_(None), RulePackRow.effective_from <= now),
            or_(RulePackRow.effective_to.is_(None), RulePackRow.effective_to > now),
        )
        scoped = session.scalar(
            select(RulePackRow)
            .where(RulePackRow.organization_id == organization_id, *active_window)
            .order_by(RulePackRow.published_at.desc())
        )
        if scoped is not None:
            return scoped
        return session.scalar(
            select(RulePackRow)
            .where(RulePackRow.organization_id.is_(None), *active_window)
            .order_by(RulePackRow.published_at.desc())
        )

    def published_policy_metadata(self, *, organization_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            pack = self._published_policy(session, organization_id=organization_id, now=now_utc())
            if pack is None:
                return None
            rules = list(
                session.scalars(
                    select(RuleDefinitionRow)
                    .where(
                        RuleDefinitionRow.rule_pack_id == pack.id,
                        RuleDefinitionRow.active.is_(True),
                    )
                    .order_by(RuleDefinitionRow.rule_id.asc())
                )
            )
            return {
                "id": pack.id,
                "name": pack.name,
                "version": pack.version,
                "scope": pack.scope,
                "rules": [
                    row_dict(rule) | {"condition": json.loads(rule.condition_json or "{}")}
                    for rule in rules
                ],
            }

    def heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        version: str,
        current_job_id: str | None = None,
        safe_error: str | None = None,
    ) -> None:
        now = now_utc()
        with self.session_factory() as session:
            row = session.scalar(
                select(WorkerHeartbeatRow).where(WorkerHeartbeatRow.worker_id == worker_id)
            )
            if row is None:
                row = WorkerHeartbeatRow(
                    id=str(uuid.uuid4()),
                    worker_id=worker_id,
                    status=status,
                    version=version,
                    current_job_id=current_job_id,
                    safe_error=safe_error,
                    started_at=now,
                    last_heartbeat_at=now,
                )
                session.add(row)
            else:
                row.status = status
                row.version = version
                row.current_job_id = current_job_id
                row.safe_error = safe_error
                row.last_heartbeat_at = now
            session.commit()

    def claim_job(self, *, worker_id: str) -> dict[str, Any] | None:
        now = now_utc()
        with self.session_factory() as session:
            stmt = (
                select(ProcessingJobRow)
                .where(
                    ProcessingJobRow.status == "QUEUED",
                    or_(
                        ProcessingJobRow.next_attempt_at.is_(None),
                        ProcessingJobRow.next_attempt_at <= now,
                    ),
                )
                .order_by(ProcessingJobRow.priority.desc(), ProcessingJobRow.queued_at.asc())
                .limit(1)
            )
            if not self.engine.url.drivername.startswith("sqlite"):
                stmt = stmt.with_for_update(skip_locked=True)
            job = session.scalar(stmt)
            if job is None:
                return None
            job.status = "RUNNING"
            job.attempts += 1
            job.started_at = now
            job.heartbeat_at = now
            session.commit()
            return row_dict(job)

    def recover_stale_jobs(self, *, stale_after_seconds: int = 180) -> int:
        cutoff = now_utc() - timedelta(seconds=max(30, stale_after_seconds))
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(ProcessingJobRow).where(
                        ProcessingJobRow.status == "RUNNING",
                        or_(
                            ProcessingJobRow.heartbeat_at.is_(None),
                            ProcessingJobRow.heartbeat_at < cutoff,
                        ),
                    )
                )
            )
            for job in rows:
                job.status = "QUEUED"
                job.next_attempt_at = now_utc()
                job.error_code = "STALE_LEASE_RECOVERED"
                job.safe_error = "The worker lease expired; the job was returned to the queue."
                job.heartbeat_at = now_utc()
            session.commit()
            return len(rows)

    def finish_job(
        self,
        *,
        job_id: str,
        success: bool,
        error_code: str | None = None,
        safe_error: str | None = None,
    ) -> None:
        now = now_utc()
        with self.session_factory() as session:
            job = session.get(ProcessingJobRow, job_id)
            if job is None:
                return
            job.completed_at = now if success else None
            job.heartbeat_at = now
            if success:
                job.status = "SUCCEEDED"
                job.error_code = None
                job.safe_error = None
                job.next_attempt_at = None
            elif job.attempts >= job.max_attempts:
                job.status = "DEAD_LETTER"
                job.error_code = error_code or "JOB_FAILED"
                job.safe_error = safe_error or "The job exceeded its retry limit."
                job.completed_at = now
                job.next_attempt_at = None
                if job.job_type == ProcessingJobType.SEND_WEBHOOK.value:
                    try:
                        delivery_id = json.loads(job.payload_json or "{}").get("delivery_id")
                    except (TypeError, ValueError):
                        delivery_id = None
                    if delivery_id:
                        delivery = session.get(WebhookDeliveryRow, str(delivery_id))
                        if delivery and delivery.organization_id == job.organization_id:
                            delivery.status = "FAILED"
                            delivery.last_error = (
                                safe_error or "The webhook delivery exceeded its retry limit."
                            )[:240]
                            delivery.next_attempt_at = None
                            if delivery.attempts >= 5:
                                subscription = session.scalar(
                                    select(WebhookSubscriptionRow).where(
                                        WebhookSubscriptionRow.id == delivery.subscription_id,
                                        WebhookSubscriptionRow.organization_id
                                        == job.organization_id,
                                    )
                                )
                                if subscription:
                                    subscription.enabled = False
                                    subscription.updated_at = now
            else:
                job.status = "QUEUED"
                job.error_code = error_code or "JOB_RETRY"
                job.safe_error = safe_error or "The job will be retried."
                backoff = min(300, 2 ** max(job.attempts, 1) * 5)
                jitter = secrets.SystemRandom().uniform(0, max(1.0, backoff * 0.25))
                job.next_attempt_at = now + timedelta(seconds=backoff + jitter)
            session.commit()

    @staticmethod
    def _current_release_snapshot(
        session: Session, *, organization_id: str, shipment_id: str
    ) -> dict[str, Any]:
        open_tasks = (
            session.scalar(
                select(func.count(ReviewTaskRow.id)).where(
                    ReviewTaskRow.shipment_id == shipment_id,
                    ReviewTaskRow.status != "RESOLVED",
                )
            )
            or 0
        )
        evaluations = list(
            session.execute(
                select(RequirementEvaluationRow, DocumentRequirementRow)
                .join(
                    DocumentRequirementRow,
                    DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                )
                .where(
                    RequirementEvaluationRow.organization_id == organization_id,
                    RequirementEvaluationRow.shipment_id == shipment_id,
                )
            )
        )
        missing_requirements = [
            requirement.name
            for evaluation, requirement in evaluations
            if requirement.status in {"REQUIRED", "ACTIVE"}
            and evaluation.result not in {"PROVIDED", "CLEAR", "NOT_APPLICABLE"}
        ]
        latest_checks: dict[str, AssuranceCheckRow] = {}
        for check in session.scalars(
            select(AssuranceCheckRow)
            .where(
                AssuranceCheckRow.organization_id == organization_id,
                AssuranceCheckRow.shipment_id == shipment_id,
            )
            .order_by(AssuranceCheckRow.created_at.desc())
        ):
            latest_checks.setdefault(check.check_type, check)
        blocking_checks = [
            check.check_type
            for check in latest_checks.values()
            if check.status in {"HOLD", "REVIEW", "PENDING", "RUNNING", "FAILED"}
        ]
        blocking_exceptions = [
            item.summary
            for item in session.scalars(
                select(ShipmentExceptionRow).where(
                    ShipmentExceptionRow.organization_id == organization_id,
                    ShipmentExceptionRow.shipment_id == shipment_id,
                    ShipmentExceptionRow.status.not_in(["RESOLVED", "CANCELLED"]),
                )
            )
            if item.severity in {"HIGH", "CRITICAL"}
        ]
        reference = session.scalar(
            select(TrustedShipmentReferenceRow).where(
                TrustedShipmentReferenceRow.organization_id == organization_id,
                TrustedShipmentReferenceRow.shipment_id == shipment_id,
            )
        )
        return build_release_snapshot(
            missing_requirements=missing_requirements,
            blocking_checks=blocking_checks,
            blocking_exceptions=blocking_exceptions,
            open_tasks=int(open_tasks),
            trusted_reference_version=reference.version if reference is not None else None,
            trusted_reference_hash=reference.content_hash if reference is not None else None,
            assurance_versions={
                check_type: (check.status, check.source_version)
                for check_type, check in latest_checks.items()
            },
        )

    def approve_release(
        self, *, organization_id: str, release_decision_id: str, user: UserRow, comment: str
    ) -> dict[str, Any]:
        now = now_utc()
        with self.session_factory() as session:
            decision = session.scalar(
                select(ReleaseDecisionRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ReleaseDecisionRow.shipment_id)
                .where(
                    ReleaseDecisionRow.id == release_decision_id,
                    ReleaseDecisionRow.organization_id == organization_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
                .with_for_update()
            )
            if decision is None:
                raise NotFoundError("Release decision was not found in this workspace.")
            shipment = session.scalar(
                select(ShipmentCaseRow)
                .where(
                    ShipmentCaseRow.id == decision.shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
                .with_for_update()
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            if decision.decision != "AUTHORIZE":
                raise GateGuardError(
                    "Only an authorization decision can receive second approval.",
                    code="INVALID_RELEASE_DECISION",
                    status_code=409,
                )
            if decision.invalidated_at is not None:
                raise GateGuardError(
                    "An invalidated release decision cannot be approved.",
                    code="RELEASE_INVALIDATED",
                    status_code=409,
                )
            if shipment.status != ShipmentStatus.RELEASE_PENDING_APPROVAL.value:
                raise GateGuardError(
                    "Shipment is not awaiting approval for this release decision.",
                    code="INVALID_RELEASE_STATE",
                    status_code=409,
                )
            if (
                snapshot_hash(
                    self._current_release_snapshot(
                        session,
                        organization_id=organization_id,
                        shipment_id=shipment.id,
                    )
                )
                != decision.evidence_hash
            ):
                decision.invalidated_at = now
                shipment.status = ShipmentStatus.RELEASE_INVALIDATED.value
                shipment.updated_at = now
                session.commit()
                raise GateGuardError(
                    "Release evidence changed and the decision was invalidated.",
                    code="RELEASE_INVALIDATED",
                    status_code=409,
                )
            if decision.decided_by == user.id:
                raise GateGuardError(
                    "A second person must approve the release decision.",
                    code="FOUR_EYES_REQUIRED",
                    status_code=409,
                )
            duplicate = session.scalar(
                select(DecisionApprovalRow).where(
                    DecisionApprovalRow.release_decision_id == release_decision_id,
                    DecisionApprovalRow.approver_user_id == user.id,
                )
            )
            if duplicate:
                raise GateGuardError(
                    "You already approved this decision.",
                    code="DUPLICATE_APPROVAL",
                    status_code=409,
                )
            row = DecisionApprovalRow(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                release_decision_id=release_decision_id,
                approver_user_id=user.id,
                approval_type="SECOND_APPROVAL",
                comment=" ".join(comment.split()),
                approved_at=now,
            )
            session.add(row)
            shipment.status = ShipmentStatus.RELEASE_AUTHORIZED.value
            shipment.release_authorized_at = now
            shipment.updated_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="release.authorized",
                    entity_type="shipment",
                    entity_id=shipment.id,
                    payload_json=json.dumps({"decision_id": decision.id, "four_eyes": True}),
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(row)
            return row_dict(row) | {"approver_name": user.display_name}

    def transition_shipment(
        self, *, organization_id: str, shipment_id: str, user: UserRow, status: str
    ) -> dict[str, Any]:
        from app.services.assurance import can_transition

        now = now_utc()
        with self.session_factory() as session:
            shipment = session.scalar(
                select(ShipmentCaseRow).where(
                    ShipmentCaseRow.id == shipment_id,
                    ShipmentCaseRow.organization_id == organization_id,
                )
            )
            if shipment is None:
                raise NotFoundError("Shipment was not found in this workspace.")
            previous_status = shipment.status
            if not can_transition(shipment.status, status):
                raise GateGuardError(
                    f"Shipment cannot move from {shipment.status} to {status}.",
                    code="INVALID_TRANSITION",
                    status_code=409,
                )
            if status == ShipmentStatus.DISPATCHED.value:
                latest = session.scalar(
                    select(ReleaseDecisionRow)
                    .where(
                        ReleaseDecisionRow.organization_id == organization_id,
                        ReleaseDecisionRow.shipment_id == shipment_id,
                        ReleaseDecisionRow.decision == "AUTHORIZE",
                        ReleaseDecisionRow.invalidated_at.is_(None),
                    )
                    .order_by(ReleaseDecisionRow.created_at.desc())
                    .with_for_update()
                )
                approved = (
                    session.scalar(
                        select(func.count(DecisionApprovalRow.id)).where(
                            DecisionApprovalRow.organization_id == organization_id,
                            DecisionApprovalRow.release_decision_id == latest.id,
                            DecisionApprovalRow.approval_type == "SECOND_APPROVAL",
                            DecisionApprovalRow.approver_user_id != latest.decided_by,
                        )
                    )
                    if latest
                    else 0
                )
                if (
                    shipment.status != ShipmentStatus.RELEASE_AUTHORIZED.value
                    or not latest
                    or not approved
                ):
                    raise GateGuardError(
                        "A current second-approved release authorization is required "
                        "before dispatch.",
                        code="FOUR_EYES_REQUIRED",
                        status_code=409,
                    )
                if (
                    snapshot_hash(
                        self._current_release_snapshot(
                            session,
                            organization_id=organization_id,
                            shipment_id=shipment_id,
                        )
                    )
                    != latest.evidence_hash
                ):
                    latest.invalidated_at = now
                    shipment.status = ShipmentStatus.RELEASE_INVALIDATED.value
                    shipment.updated_at = now
                    session.commit()
                    raise GateGuardError(
                        "Release evidence changed and cannot be dispatched.",
                        code="RELEASE_INVALIDATED",
                        status_code=409,
                    )
                shipment.dispatched_at = now
            if status == ShipmentStatus.CLOSED.value:
                shipment.closed_at = now
            shipment.status = status
            shipment.updated_at = now
            session.add(
                DomainEventRow(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    event_type="shipment.status.changed",
                    entity_type="shipment",
                    entity_id=shipment_id,
                    payload_json=json.dumps({"from": previous_status, "to": status}),
                    created_at=now,
                )
            )
            session.commit()
            return row_dict(shipment)

    def overview(self, *, organization_id: str, start: datetime, end: datetime) -> dict[str, Any]:
        with self.session_factory() as session:
            shipment_count = (
                session.scalar(
                    select(func.count(ShipmentCaseRow.id)).where(
                        ShipmentCaseRow.organization_id == organization_id,
                        ShipmentCaseRow.created_at >= start,
                        ShipmentCaseRow.created_at < end,
                    )
                )
                or 0
            )
            active = (
                session.scalar(
                    select(func.count(ShipmentCaseRow.id)).where(
                        ShipmentCaseRow.organization_id == organization_id,
                        ShipmentCaseRow.status.not_in(
                            [ShipmentStatus.CLOSED.value, ShipmentStatus.DISPATCHED.value]
                        ),
                    )
                )
                or 0
            )
            open_exceptions = (
                session.scalar(
                    select(func.count(ShipmentExceptionRow.id)).where(
                        ShipmentExceptionRow.organization_id == organization_id,
                        ShipmentExceptionRow.status.not_in(["RESOLVED", "CANCELLED"]),
                    )
                )
                or 0
            )
            overdue = (
                session.scalar(
                    select(func.count(ShipmentExceptionRow.id)).where(
                        ShipmentExceptionRow.organization_id == organization_id,
                        ShipmentExceptionRow.due_at < now_utc(),
                        ShipmentExceptionRow.status.not_in(["RESOLVED", "CANCELLED"]),
                    )
                )
                or 0
            )
            authorized = (
                session.scalar(
                    select(func.count(ShipmentCaseRow.id)).where(
                        ShipmentCaseRow.organization_id == organization_id,
                        ShipmentCaseRow.status == ShipmentStatus.RELEASE_AUTHORIZED.value,
                    )
                )
                or 0
            )
            daily_events = list(
                session.execute(
                    select(
                        func.date(DomainEventRow.created_at),
                        DomainEventRow.event_type,
                        func.count(),
                    )
                    .where(
                        DomainEventRow.organization_id == organization_id,
                        DomainEventRow.created_at >= start,
                        DomainEventRow.created_at < end,
                    )
                    .group_by(func.date(DomainEventRow.created_at), DomainEventRow.event_type)
                    .order_by(func.date(DomainEventRow.created_at).asc())
                )
            )
            event_buckets: dict[str, list[tuple[int, int]]] = {}
            for day, event_type, count in daily_events:
                day_value = datetime.fromisoformat(str(day)).replace(tzinfo=UTC)
                event_buckets.setdefault(str(event_type), []).append(
                    (int(day_value.timestamp() * 1000), int(count))
                )

            def status_breakdown(
                model: Any, field: Any, timestamp: Any
            ) -> list[dict[str, int | str]]:
                rows = session.execute(
                    select(field, func.count())
                    .where(
                        model.organization_id == organization_id,
                        timestamp >= start,
                        timestamp < end,
                    )
                    .group_by(field)
                    .order_by(func.count().desc(), field.asc())
                )
                return [{"key": str(key), "value": int(value)} for key, value in rows]

            # Data names are semantic. The client owns all Kumo palette decisions.
            series = [
                {
                    "key": event_type,
                    "name": event_type.replace(".", " ").title(),
                    "data": points,
                }
                for event_type, points in sorted(event_buckets.items())
            ]
            return {
                "active_shipments": int(active),
                "assessments": int(shipment_count),
                "open_exceptions": int(open_exceptions),
                "overdue_work": int(overdue),
                "release_authorized": int(authorized),
                "series": series,
                "breakdowns": {
                    "assurance_status": status_breakdown(
                        AssuranceCheckRow, AssuranceCheckRow.status, AssuranceCheckRow.created_at
                    ),
                    "document_extraction": status_breakdown(
                        DocumentVersionRow,
                        DocumentVersionRow.extraction_status,
                        DocumentVersionRow.uploaded_at,
                    ),
                    "exception_severity": status_breakdown(
                        ShipmentExceptionRow,
                        ShipmentExceptionRow.severity,
                        ShipmentExceptionRow.created_at,
                    ),
                    "screening_result": status_breakdown(
                        ScreeningRunRow, ScreeningRunRow.result, ScreeningRunRow.screened_at
                    ),
                },
            }
