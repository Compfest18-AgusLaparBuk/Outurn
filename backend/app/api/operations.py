from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.auth.dependencies import current_user, require_role
from app.core.config import get_settings
from app.core.errors import OuturnError
from app.repositories.operations import ApiIdempotencyRow, DomainEventRow, OperationsRepository
from app.repositories.reconciliations import UserRow
from app.services.document_storage import DocumentStorage
from app.services.file_validation import validate_upload

router = APIRouter()

_SERVICE_RATE_LIMIT: dict[str, tuple[int, float]] = {}
_SERVICE_RATE_LIMIT_LOCK = threading.Lock()


def enforce_service_rate_limit(principal: Any) -> None:
    """Bound partner API traffic per service account without touching BFF limits."""
    now = time.monotonic()
    key = str(principal.service_account_id)
    with _SERVICE_RATE_LIMIT_LOCK:
        count, window = _SERVICE_RATE_LIMIT.get(key, (0, now))
        if now - window >= 60:
            count, window = 0, now
        if count >= 120:
            raise OuturnError(
                "Service API rate limit exceeded.", code="RATE_LIMITED", status_code=429
            )
        _SERVICE_RATE_LIMIT[key] = (count + 1, window)
        if len(_SERVICE_RATE_LIMIT) > 10_000:
            expired = [
                item for item, (_, started) in _SERVICE_RATE_LIMIT.items() if now - started >= 60
            ]
            for item in expired[:1_000]:
                _SERVICE_RATE_LIMIT.pop(item, None)


@lru_cache
def get_operations() -> OperationsRepository:
    settings = get_settings()
    return OperationsRepository(
        settings.database_url, auto_create_schema=settings.app_env.casefold() != "production"
    )


def organization(request: Request, user: UserRow) -> Any:
    return get_operations().organization_for(user, request.headers.get("x-outurn-organization"))


def audit(
    request: Request,
    event_type: str,
    entity_type: str,
    entity_id: str,
    user: UserRow,
    metadata: dict[str, Any] | None = None,
) -> None:
    workspace = organization(request, user)
    from app.api.routes import get_repository

    get_repository().record_audit(
        event_type,
        entity_type,
        entity_id=entity_id,
        actor=user,
        organization_id=workspace.id,
        metadata=metadata or {},
        request_id=request.state.request_id,
    )


class SettingsPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class RetentionLegalHoldPayload(BaseModel):
    reason: str = Field(default="", max_length=500)
    active: bool = True


class ConnectionPayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    type: str = Field(min_length=2, max_length=32)
    configuration: dict[str, Any] = Field(default_factory=dict)
    credential_reference: str | None = Field(default=None, max_length=160)


class ConnectionCredentialPayload(BaseModel):
    credential_reference: str | None = Field(default=None, max_length=160)


class WebhookPayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    endpoint: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(default_factory=list, max_length=20)


class WebhookTestPayload(BaseModel):
    event_type: str = Field(default="webhook.test", min_length=2, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class ServiceAccountPayload(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    scopes: list[str] = Field(default_factory=lambda: ["shipment.read"], max_length=20)
    expires_at: datetime | None = None


class ReferenceDataPayload(BaseModel):
    category: str = Field(min_length=2, max_length=40)
    code: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="Workspace maintained", min_length=2, max_length=160)
    version: str = Field(default="1", min_length=1, max_length=40)


class RuleSimulationPayload(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


class DocumentMetadataPayload(BaseModel):
    shipment_id: str = Field(min_length=1, max_length=36)
    document_type: str = Field(min_length=2, max_length=48)
    filename: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(default="application/octet-stream", max_length=120)
    size_bytes: int = Field(default=0, ge=0, le=50_000_000)
    sha256: str = Field(default="", max_length=64)
    requirement_id: str | None = Field(default=None, max_length=36)


class ExceptionActionPayload(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    assigned_to: str | None = Field(default=None, max_length=36)
    resolution_code: str | None = Field(default=None, max_length=64)
    resolution_note: str | None = Field(default=None, max_length=2000)


class ScreeningAdjudicationPayload(BaseModel):
    disposition: Literal["CLEAR", "MATCH", "FALSE_POSITIVE", "REQUIRES_REVIEW"]
    comment: str = Field(min_length=2, max_length=1000)


class ExceptionCommentPayload(BaseModel):
    body: str = Field(min_length=2, max_length=2000)


class ApprovalPayload(BaseModel):
    comment: str = Field(min_length=2, max_length=1000)


class ShipmentLifecyclePayload(BaseModel):
    status: str = Field(min_length=2, max_length=32)


class TrustedReferencePayload(BaseModel):
    order_reference: str | None = Field(default=None, max_length=120)
    shipment_reference: str | None = Field(default=None, max_length=120)
    expected_shipper: str | None = Field(default=None, max_length=160)
    expected_recipient: str | None = Field(default=None, max_length=160)
    expected_destination: str | None = Field(default=None, max_length=160)
    expected_currency: str | None = Field(default=None, max_length=8)
    expected_total: float | None = Field(default=None, ge=0)
    source_system: str = Field(default="Workspace entry", max_length=80)
    source_type: str = Field(default="MANUAL_AUTHORITATIVE_ENTRY", max_length=40)
    source_record_id: str | None = Field(default=None, max_length=120)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class PartyPayload(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    address: str | None = Field(default=None, max_length=1000)
    city: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    tax_identifier: str | None = Field(default=None, max_length=100)
    external_identifier: str | None = Field(default=None, max_length=100)
    shipment_id: str | None = Field(default=None, max_length=36)
    role: str = Field(default="OTHER", max_length=32)


class ItemPayload(BaseModel):
    shipment_id: str = Field(min_length=1, max_length=36)
    line_number: int = Field(ge=1, le=100000)
    sku: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    quantity: float = Field(ge=0)
    unit_of_measure: str = Field(default="unit", max_length=24)
    unit_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    line_total: float | None = Field(default=None, ge=0)
    country_of_origin: str | None = Field(default=None, min_length=2, max_length=2)
    hs_code: str | None = Field(default=None, max_length=32)
    gross_weight: float | None = Field(default=None, ge=0)
    net_weight: float | None = Field(default=None, ge=0)
    dangerous_goods: bool = False
    un_number: str | None = Field(default=None, max_length=16)
    proper_shipping_name: str | None = Field(default=None, max_length=240)
    hazard_class: str | None = Field(default=None, max_length=32)
    packing_group: str | None = Field(default=None, max_length=16)
    special_handling: str | None = Field(default=None, max_length=2000)
    package_count: int | None = Field(default=None, ge=0)


class TransportPayload(BaseModel):
    shipment_id: str = Field(min_length=1, max_length=36)
    sequence: int = Field(default=1, ge=1, le=100)
    mode: str = Field(min_length=2, max_length=24)
    carrier: str | None = Field(default=None, max_length=160)
    origin: str | None = Field(default=None, max_length=160)
    destination: str | None = Field(default=None, max_length=160)
    planned_departure: datetime | None = None
    planned_arrival: datetime | None = None
    actual_departure: datetime | None = None
    actual_arrival: datetime | None = None
    vessel: str | None = Field(default=None, max_length=120)
    voyage: str | None = Field(default=None, max_length=80)
    flight: str | None = Field(default=None, max_length=80)
    vehicle_reference: str | None = Field(default=None, max_length=80)


@router.get("/api/organizations")
def organizations(user: UserRow = Depends(current_user)):
    return {"items": get_operations().list_organizations(user)}


@router.get("/api/workspace-context")
def workspace_context(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    role = get_operations().membership_role_for(organization_id=org.id, user_id=user.id)
    permissions = {
        "operator": {
            "workspace.read",
            "shipment.read",
            "shipment.write",
            "assurance.read",
            "exception.write",
            "screening.write",
            "notification.write",
        },
        "supervisor": {
            "workspace.read",
            "shipment.read",
            "shipment.write",
            "assurance.read",
            "exception.write",
            "screening.write",
            "release.approve",
            "jobs.manage",
            "integrations.read",
            "notification.write",
        },
        "admin": {"*"},
    }[role]
    return {
        "organization": {"id": org.id, "name": org.name, "code": org.code},
        "role": role,
        "permissions": sorted(permissions),
    }


@router.get("/api/recents")
def recents(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return {"items": get_operations().recents(organization_id=org.id, user_id=user.id)}


@router.post("/api/recents")
def record_recent(payload: dict[str, str], request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    required = {"object_type", "object_id", "label", "href"}
    if not required.issubset(payload):
        raise OuturnError(
            "Recent object metadata is incomplete.", code="VALIDATION_ERROR", status_code=422
        )
    get_operations().record_recent(
        organization_id=org.id, user_id=user.id, **{key: payload[key] for key in required}
    )
    return {"status": "recorded"}


@router.get("/api/search")
def search(
    request: Request,
    q: str = Query(min_length=1, max_length=120),
    types: list[str] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {
        "items": get_operations().search(
            organization_id=org.id,
            user=user,
            workspace_role=get_operations().membership_role_for(
                organization_id=org.id, user_id=user.id
            ),
            query=q,
            limit=limit,
            types=set(types or []),
        )
    }


@router.get("/api/shipments/{shipment_id}/workspace")
def shipment_workspace(shipment_id: str, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    detail = get_operations().detail(organization_id=org.id, shipment_id=shipment_id)
    get_operations().record_recent(
        organization_id=org.id,
        user_id=user.id,
        object_type="shipment",
        object_id=shipment_id,
        label=detail["shipment"]["internal_reference"],
        href=f"/shipments/{shipment_id}",
    )
    return detail


@router.get("/api/shipments/{shipment_id}/release-gate")
def shipment_release_gate(
    shipment_id: str, request: Request, user: UserRow = Depends(current_user)
):
    org = organization(request, user)
    return get_operations().release_gate_snapshot(organization_id=org.id, shipment_id=shipment_id)


@router.post("/api/shipments/{shipment_id}/assess", status_code=202)
def assess_shipment(shipment_id: str, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    result = get_operations().run_assessment(
        organization_id=org.id, shipment_id=shipment_id, user=user
    )
    audit(request, "assessment.started", "shipment", shipment_id, user, result)
    return result


@router.get("/api/shipments/{shipment_id}/trusted-reference")
def trusted_reference(shipment_id: str, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    from app.repositories.reconciliations import TrustedShipmentReferenceRow

    with get_operations().session_factory() as session:
        reference = session.scalar(
            select(TrustedShipmentReferenceRow).where(
                TrustedShipmentReferenceRow.shipment_id == shipment_id,
                TrustedShipmentReferenceRow.organization_id == org.id,
            )
        )
        if reference is None:
            raise OuturnError(
                "Trusted source has not been recorded.", code="NOT_FOUND", status_code=404
            )
        return {
            "reference": {
                column.name: getattr(reference, column.name)
                for column in reference.__table__.columns
            }
        }


@router.put("/api/shipments/{shipment_id}/trusted-reference")
def save_trusted_reference(
    shipment_id: str,
    payload: TrustedReferencePayload,
    request: Request,
    user: UserRow = Depends(require_role("supervisor", "admin")),
):
    org = organization(request, user)
    result = get_operations().save_trusted_reference(
        organization_id=org.id,
        shipment_id=shipment_id,
        user=user,
        payload=payload.model_dump(),
    )
    audit(request, "trusted_reference.updated", "shipment", shipment_id, user)
    return result


@router.get("/api/parties")
def parties(request: Request, q: str | None = None, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return {"items": get_operations().list_parties(organization_id=org.id, query=q)}


@router.post("/api/parties", status_code=201)
def create_party(payload: PartyPayload, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    result = get_operations().create_party(
        organization_id=org.id, user=user, payload=payload.model_dump()
    )
    audit(request, "party.created", "party", result["id"], user)
    return result


@router.get("/api/products")
def products(request: Request, q: str | None = None, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return {"items": get_operations().list_items(organization_id=org.id, query=q)}


@router.post("/api/products", status_code=201)
def create_product(payload: ItemPayload, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    result = get_operations().create_item(organization_id=org.id, payload=payload.model_dump())
    audit(request, "shipment_item.created", "shipment_item", result["id"], user)
    return result


@router.get("/api/items")
def items(
    request: Request,
    q: str | None = None,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {"items": get_operations().list_items(organization_id=org.id, query=q)}


@router.post("/api/items", status_code=201)
def create_item(
    payload: ItemPayload,
    request: Request,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    result = get_operations().create_item(organization_id=org.id, payload=payload.model_dump())
    audit(request, "shipment_item.created", "shipment_item", result["id"], user)
    return result


@router.get("/api/transport")
def transport(
    request: Request, shipment_id: str | None = None, user: UserRow = Depends(current_user)
):
    org = organization(request, user)
    return {
        "items": get_operations().list_transport(organization_id=org.id, shipment_id=shipment_id)
    }


@router.post("/api/transport", status_code=201)
def create_transport(
    payload: TransportPayload, request: Request, user: UserRow = Depends(current_user)
):
    org = organization(request, user)
    result = get_operations().create_transport(organization_id=org.id, payload=payload.model_dump())
    audit(request, "transport_leg.created", "transport_leg", result["id"], user)
    return result


@router.get("/api/documents")
def documents(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    document_type: str | None = None,
    extraction_status: str | None = None,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {
        "items": get_operations().list_documents(
            organization_id=org.id,
            query=q,
            status=status,
            document_type=document_type,
            extraction_status=extraction_status,
        )
    }


@router.post("/api/documents", status_code=410)
def create_document_metadata_legacy(
    _: DocumentMetadataPayload,
    __: Request,
    ___: UserRow = Depends(current_user),
):
    """Reject metadata-only document creation; vault uploads must include validated bytes."""
    raise OuturnError(
        "Document metadata cannot be created without a validated vault upload.",
        code="DOCUMENT_UPLOAD_REQUIRED",
        status_code=410,
    )


@router.post("/api/documents/upload", status_code=201)
async def upload_document(
    request: Request,
    shipment_id: str = Form(..., min_length=1, max_length=36),
    document_type: str = Form(..., min_length=2, max_length=48),
    document_id: str | None = Form(default=None, max_length=36),
    requirement_id: str | None = Form(default=None, max_length=36),
    file: UploadFile = File(...),
    user: UserRow = Depends(current_user),
):
    settings = get_settings()
    safe_upload = await validate_upload(
        file,
        settings.max_upload_bytes,
        settings.max_image_pixels,
    )
    if safe_upload.media_type not in {
        item.split(";", 1)[0].strip().lower() for item in settings.document_allowed_mime_types
    }:
        raise OuturnError(
            "This file type is not allowed by the workspace document policy.",
            code="INVALID_MIME_TYPE",
            status_code=422,
        )
    org = organization(request, user)
    storage_key = f"{org.id}/{shipment_id}/{uuid.uuid4()}.bin"
    storage = DocumentStorage(settings.document_storage_root)
    size_bytes, sha256 = storage.write(
        storage_key,
        BytesIO(safe_upload.data),
        max_bytes=settings.max_upload_bytes,
    )
    try:
        result = get_operations().create_document_version(
            organization_id=org.id,
            user=user,
            shipment_id=shipment_id,
            document_type=document_type,
            filename=safe_upload.filename,
            mime_type=safe_upload.media_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_key=storage_key,
            document_id=document_id,
            requirement_id=requirement_id,
        )
    except Exception:
        storage.path_for(storage_key).unlink(missing_ok=True)
        raise
    audit(
        request, "document.uploaded", "document", result["id"], user, {"shipment_id": shipment_id}
    )
    return result


@router.get("/api/documents/{document_id}/download")
def download_document(
    document_id: str,
    request: Request,
    version: int | None = Query(default=None, ge=1),
    user: UserRow = Depends(current_user),
):
    settings = get_settings()
    org = organization(request, user)
    metadata = get_operations().document_content_metadata(
        organization_id=org.id, document_id=document_id, version=version
    )
    storage = DocumentStorage(settings.document_storage_root)
    stream = storage.open(metadata["storage_key"])
    filename = re.sub(r"[\x00-\x1f\x7f\"]", "", Path(str(metadata["filename"])).name).strip()
    filename = filename or "document"
    return StreamingResponse(
        stream,
        media_type=metadata["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(stream.close),
    )


@router.get("/api/requirements")
def requirements(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    with get_operations().session_factory() as session:
        from app.repositories.operations import (
            DocumentRequirementRow,
            RequirementEvaluationRow,
            ShipmentCaseRow,
        )

        rows = list(
            session.execute(
                select(RequirementEvaluationRow, DocumentRequirementRow, ShipmentCaseRow)
                .join(
                    DocumentRequirementRow,
                    DocumentRequirementRow.id == RequirementEvaluationRow.requirement_id,
                )
                .join(ShipmentCaseRow, ShipmentCaseRow.id == RequirementEvaluationRow.shipment_id)
                .where(RequirementEvaluationRow.organization_id == org.id)
                .order_by(RequirementEvaluationRow.evaluated_at.desc())
                .limit(200)
            )
        )
        return {
            "items": [
                {
                    "evaluation": {
                        column.name: getattr(evaluation, column.name)
                        for column in evaluation.__table__.columns
                    },
                    "requirement": {
                        column.name: getattr(requirement, column.name)
                        for column in requirement.__table__.columns
                    },
                    "shipment_reference": shipment.internal_reference,
                }
                for evaluation, requirement, shipment in rows
            ]
        }


@router.get("/api/assurance")
def assurance(
    request: Request,
    check_type: str | None = None,
    status: str | None = None,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {
        "items": get_operations().list_checks(
            organization_id=org.id, check_type=check_type, status=status
        )
    }


@router.get("/api/exceptions")
def exceptions(
    request: Request,
    status: str | None = None,
    mine: bool = False,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {
        "items": get_operations().list_exceptions(
            organization_id=org.id, status=status, mine=user.id if mine else None
        )
    }


@router.patch("/api/exceptions/{exception_id}")
def update_exception(
    exception_id: str,
    payload: ExceptionActionPayload,
    request: Request,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    result = get_operations().update_exception(
        organization_id=org.id,
        exception_id=exception_id,
        user=user,
        **payload.model_dump(),
    )
    audit(
        request, "exception.updated", "exception", exception_id, user, {"status": result["status"]}
    )
    return result


@router.post("/api/exceptions/{exception_id}/comments", status_code=201)
def comment_exception(
    exception_id: str,
    payload: ExceptionCommentPayload,
    request: Request,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    result = get_operations().add_exception_comment(
        organization_id=org.id, exception_id=exception_id, user=user, body=payload.body
    )
    audit(request, "exception.comment_added", "exception", exception_id, user)
    return result


@router.get("/api/releases")
def releases(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return {"items": get_operations().list_releases(organization_id=org.id)}


@router.post("/api/releases/{release_decision_id}/approve", status_code=201)
def approve_release(
    release_decision_id: str,
    payload: ApprovalPayload,
    request: Request,
    user: UserRow = Depends(require_role("supervisor", "admin")),
):
    org = organization(request, user)
    result = get_operations().approve_release(
        organization_id=org.id,
        release_decision_id=release_decision_id,
        user=user,
        comment=payload.comment,
    )
    audit(request, "release.second_approval", "release_decision", release_decision_id, user)
    return result


@router.post("/api/shipments/{shipment_id}/lifecycle")
def transition_shipment(
    shipment_id: str,
    payload: ShipmentLifecyclePayload,
    request: Request,
    user: UserRow = Depends(require_role("supervisor", "admin")),
):
    org = organization(request, user)
    result = get_operations().transition_shipment(
        organization_id=org.id, shipment_id=shipment_id, user=user, status=payload.status
    )
    audit(
        request,
        "shipment.status_changed",
        "shipment",
        shipment_id,
        user,
        {"status": payload.status},
    )
    return result


@router.get("/api/screening")
def screening(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    with get_operations().session_factory() as session:
        from sqlalchemy import select

        from app.repositories.operations import ScreeningRunRow, ShipmentCaseRow, TradePartyRow

        rows = list(
            session.execute(
                select(ScreeningRunRow, TradePartyRow, ShipmentCaseRow)
                .join(TradePartyRow, TradePartyRow.id == ScreeningRunRow.party_id)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ScreeningRunRow.shipment_id)
                .where(ScreeningRunRow.organization_id == org.id)
                .order_by(ScreeningRunRow.screened_at.desc())
                .limit(200)
            )
        )
        return {
            "items": [
                {
                    "run": {
                        column.name: getattr(run, column.name) for column in run.__table__.columns
                    },
                    "party": party.legal_name,
                    "shipment_reference": shipment.internal_reference,
                }
                for run, party, shipment in rows
            ]
        }


@router.post("/api/shipments/{shipment_id}/screening", status_code=202)
def run_screening(
    shipment_id: str,
    request: Request,
    party_id: str | None = Query(default=None, max_length=36),
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    result = get_operations().run_screening(
        organization_id=org.id, shipment_id=shipment_id, party_id=party_id, user=user
    )
    audit(
        request, "screening.completed", "shipment", shipment_id, user, {"result": result["result"]}
    )
    return result


@router.patch("/api/screening/{run_id}/adjudication")
def adjudicate_screening(
    run_id: str,
    payload: ScreeningAdjudicationPayload,
    request: Request,
    user: UserRow = Depends(require_role("supervisor", "admin")),
):
    org = organization(request, user)
    result = get_operations().adjudicate_screening(
        organization_id=org.id,
        run_id=run_id,
        user=user,
        disposition=payload.disposition,
        comment=payload.comment,
    )
    audit(request, "screening.adjudicated", "screening_run", run_id, user)
    return result


@router.get("/api/dangerous-goods")
def dangerous_goods(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    with get_operations().session_factory() as session:
        from sqlalchemy import select

        from app.repositories.operations import ShipmentCaseRow, ShipmentItemRow

        rows = list(
            session.execute(
                select(ShipmentItemRow, ShipmentCaseRow)
                .join(ShipmentCaseRow, ShipmentCaseRow.id == ShipmentItemRow.shipment_id)
                .where(
                    ShipmentItemRow.organization_id == org.id,
                    ShipmentItemRow.dangerous_goods.is_(True),
                )
                .order_by(ShipmentItemRow.updated_at.desc())
                .limit(200)
            )
        )
        return {
            "items": [
                {
                    "item": {
                        column.name: getattr(item, column.name) for column in item.__table__.columns
                    },
                    "shipment_reference": shipment.internal_reference,
                    "assurance": "REVIEW"
                    if not item.un_number or not item.proper_shipping_name or not item.hazard_class
                    else "CLEAR",
                }
                for item, shipment in rows
            ]
        }


@router.get("/api/analytics/summary")
def analytics_summary(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return get_operations().overview(
        organization_id=org.id,
        start=datetime.now(UTC) - timedelta(days=days),
        end=datetime.now(UTC),
    )


@router.get("/api/analytics/timeseries")
def analytics_timeseries(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    summary = get_operations().overview(
        organization_id=org.id,
        start=datetime.now(UTC) - timedelta(days=days),
        end=datetime.now(UTC),
    )
    return {
        "series": summary["series"],
        "days": days,
        "message": "Not enough data" if not summary["series"] else None,
    }


@router.get("/api/observability")
def observability(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    settings = get_settings()
    jobs = get_operations().list_jobs(organization_id=org.id)
    now = datetime.now(UTC)
    active_jobs = [item for item in jobs if item["status"] in {"QUEUED", "RUNNING"}]
    try:
        with get_operations().engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        database_status = "healthy"
    except Exception:
        database_status = "unavailable"
    configured_extraction = settings.extraction_provider in {"local", "paddle"} or bool(
        settings.openai_api_key
    ) or bool(settings.openrouter_api_key)
    connections = get_operations().list_connections(organization_id=org.id)
    webhooks = get_operations().list_webhooks(organization_id=org.id)
    from app.repositories.operations import WorkerHeartbeatRow

    with get_operations().session_factory() as session:
        workers = list(
            session.scalars(
                select(WorkerHeartbeatRow).order_by(WorkerHeartbeatRow.last_heartbeat_at.desc())
            )
        )
    live_workers = [
        worker
        for worker in workers
        if (now - worker.last_heartbeat_at.replace(tzinfo=UTC)).total_seconds() < 120
    ]
    succeeded_jobs = sum(item["status"] == "SUCCEEDED" for item in jobs)
    failed_jobs = sum(item["status"] in {"FAILED", "DEAD_LETTER"} for item in jobs)
    return {
        "application": "healthy" if database_status == "healthy" else "degraded",
        "database": database_status,
        "worker": "healthy" if live_workers else "not_running",
        "workers": [
            {
                "worker_id": worker.worker_id,
                "status": worker.status,
                "version": worker.version,
                "last_heartbeat_at": worker.last_heartbeat_at,
                "current_job_id": worker.current_job_id,
            }
            for worker in live_workers
        ],
        "extraction": "configured" if configured_extraction else "needs_setup",
        "webhook": (
            "configured_queued" if any(item["enabled"] for item in webhooks) else "not_configured"
        ),
        "connections": {
            "total": len(connections),
            "enabled": sum(item["status"] == "ENABLED" for item in connections),
        },
        "jobs": jobs[:20],
        "queue_depth": len(active_jobs),
        "jobs_succeeded": succeeded_jobs,
        "jobs_failed": failed_jobs,
        "oldest_queued_job": next(
            (item for item in reversed(jobs) if item["status"] == "QUEUED"), None
        ),
    }


@router.get("/api/integrations/connections")
def connections(request: Request, user: UserRow = Depends(require_role("admin", "supervisor"))):
    org = organization(request, user)
    return {"items": get_operations().list_connections(organization_id=org.id)}


@router.post("/api/integrations/connections", status_code=201)
def create_connection(
    payload: ConnectionPayload, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().create_connection(
        organization_id=org.id, user=user, payload=payload.model_dump()
    )
    audit(request, "integration.connection_created", "integration_connection", result["id"], user)
    return result


@router.post("/api/integrations/connections/{connection_id}/validate")
def validate_connection(
    connection_id: str, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().connection_action(
        organization_id=org.id, connection_id=connection_id, action="VALIDATE"
    )
    audit(
        request, "integration.connection_validated", "integration_connection", connection_id, user
    )
    return result


@router.post("/api/integrations/connections/{connection_id}/test")
def test_connection(
    connection_id: str, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().connection_action(
        organization_id=org.id, connection_id=connection_id, action="TEST"
    )
    audit(request, "integration.connection_tested", "integration_connection", connection_id, user)
    return result


@router.post("/api/integrations/connections/{connection_id}/{action}")
def connection_lifecycle(
    connection_id: str,
    action: str,
    request: Request,
    payload: ConnectionCredentialPayload | None = None,
    user: UserRow = Depends(require_role("admin")),
):
    if action not in {"enable", "disable", "rotate"}:
        raise OuturnError(
            "Unsupported connection action.", code="VALIDATION_ERROR", status_code=422
        )
    org = organization(request, user)
    result = get_operations().connection_action(
        organization_id=org.id,
        connection_id=connection_id,
        action=action.upper(),
        credential_reference=payload.credential_reference if payload else None,
    )
    audit(
        request, f"integration.connection_{action}d", "integration_connection", connection_id, user
    )
    return result


@router.delete("/api/integrations/connections/{connection_id}")
def delete_connection(
    connection_id: str, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().connection_action(
        organization_id=org.id, connection_id=connection_id, action="DELETE"
    )
    audit(request, "integration.connection_deleted", "integration_connection", connection_id, user)
    return result


@router.get("/api/integrations/webhooks")
def webhooks(request: Request, user: UserRow = Depends(require_role("admin", "supervisor"))):
    org = organization(request, user)
    return {"items": get_operations().list_webhooks(organization_id=org.id)}


@router.post("/api/integrations/webhooks", status_code=201)
def create_webhook(
    payload: WebhookPayload, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().create_webhook(organization_id=org.id, payload=payload.model_dump())
    audit(request, "integration.webhook_created", "webhook", result["subscription"]["id"], user)
    return result


@router.post("/api/integrations/webhooks/{subscription_id}/test", status_code=202)
def queue_webhook_test(
    subscription_id: str,
    payload: WebhookTestPayload,
    request: Request,
    user: UserRow = Depends(require_role("admin")),
):
    org = organization(request, user)
    result = get_operations().queue_webhook_delivery(
        organization_id=org.id,
        subscription_id=subscription_id,
        event_type=payload.event_type,
        payload={"test": True, **payload.payload},
        allow_unlisted_test=True,
    )
    audit(request, "integration.webhook_delivery_queued", "webhook", subscription_id, user)
    return result


@router.get("/api/integrations/webhooks/{subscription_id}/deliveries")
def webhook_deliveries(
    subscription_id: str,
    request: Request,
    user: UserRow = Depends(require_role("admin", "supervisor")),
):
    org = organization(request, user)
    return {
        "items": get_operations().list_webhook_deliveries(
            organization_id=org.id, subscription_id=subscription_id
        )
    }


@router.post("/api/integrations/webhooks/{subscription_id}/{action}")
def webhook_lifecycle(
    subscription_id: str,
    action: str,
    request: Request,
    user: UserRow = Depends(require_role("admin")),
):
    if action not in {"enable", "disable", "rotate", "delete"}:
        raise OuturnError(
            "Unsupported webhook action.", code="VALIDATION_ERROR", status_code=422
        )
    org = organization(request, user)
    result = get_operations().webhook_action(
        organization_id=org.id, subscription_id=subscription_id, action=action.upper()
    )
    audit(request, f"integration.webhook_{action}d", "webhook", subscription_id, user)
    return result


@router.post("/api/integrations/webhooks/deliveries/{delivery_id}/retry", status_code=202)
def retry_webhook_delivery(
    delivery_id: str, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().retry_webhook_delivery(
        organization_id=org.id, delivery_id=delivery_id
    )
    audit(request, "integration.webhook_delivery_retried", "webhook_delivery", delivery_id, user)
    return result


@router.get("/api/integrations/jobs")
def jobs(
    request: Request,
    status: str | None = None,
    user: UserRow = Depends(require_role("admin", "supervisor")),
):
    org = organization(request, user)
    return {"items": get_operations().list_jobs(organization_id=org.id, status=status)}


@router.post("/api/integrations/jobs/{job_id}/retry", status_code=202)
def retry_job(
    job_id: str,
    request: Request,
    user: UserRow = Depends(require_role("admin", "supervisor")),
):
    org = organization(request, user)
    result = get_operations().retry_job(organization_id=org.id, job_id=job_id)
    audit(request, "integration.job_retried", "processing_job", job_id, user)
    return result


@router.get("/api/settings/workspace")
def workspace_settings(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return get_operations().settings(organization_id=org.id)


@router.patch("/api/settings/workspace")
def save_workspace_settings(
    payload: SettingsPayload, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().save_settings(
        organization_id=org.id, user=user, values=payload.values
    )
    get_operations().record_recent(
        organization_id=org.id,
        user_id=user.id,
        object_type="settings",
        object_id=org.id,
        label="Workspace settings",
        href="/settings",
    )
    audit(
        request,
        "workspace.settings_updated",
        "organization",
        org.id,
        user,
        {"keys": list(payload.values)},
    )
    return result


@router.post("/api/settings/retention/dry-run")
def retention_dry_run(request: Request, user: UserRow = Depends(require_role("admin"))):
    org = organization(request, user)
    return get_operations().retention_dry_run(organization_id=org.id)


@router.post("/api/settings/retention/cleanup")
def retention_cleanup(request: Request, user: UserRow = Depends(require_role("admin"))):
    org = organization(request, user)
    result = get_operations().cleanup_retention(organization_id=org.id)
    audit(request, "retention.cleanup", "organization", org.id, user, result.get("deleted", {}))
    return result


@router.post("/api/settings/retention/legal-holds/{shipment_id}")
def set_retention_legal_hold(
    shipment_id: str,
    payload: RetentionLegalHoldPayload,
    request: Request,
    user: UserRow = Depends(require_role("supervisor", "admin")),
):
    org = organization(request, user)
    result = get_operations().set_legal_hold(
        organization_id=org.id,
        shipment_id=shipment_id,
        user=user,
        active=payload.active,
        reason=payload.reason,
    )
    audit(request, "retention.legal_hold_updated", "shipment", shipment_id, user)
    return result


@router.get("/api/rule-packs")
def rule_packs(request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    with get_operations().session_factory() as session:
        from sqlalchemy import or_, select
        from sqlalchemy.orm import aliased

        from app.repositories.operations import RulePackRow

        publisher = aliased(UserRow)
        rows = list(
            session.execute(
                select(RulePackRow, publisher)
                .outerjoin(publisher, publisher.id == RulePackRow.published_by)
                .where(
                    or_(
                        RulePackRow.organization_id == org.id, RulePackRow.organization_id.is_(None)
                    )
                )
                .order_by(RulePackRow.updated_at.desc())
            )
        )
        return {
            "items": [
                {
                    **{
                        column.name: getattr(pack, column.name) for column in pack.__table__.columns
                    },
                    "source": "WORKSPACE" if pack.organization_id else "SHARED_POLICY",
                    "published_by_display_name": user_row.display_name if user_row else None,
                }
                for pack, user_row in rows
            ]
        }


@router.get("/api/rule-packs/{rule_pack_id}")
def rule_pack_detail(rule_pack_id: str, request: Request, user: UserRow = Depends(current_user)):
    org = organization(request, user)
    return get_operations().rule_pack_detail(organization_id=org.id, rule_pack_id=rule_pack_id)


@router.post("/api/rule-packs/{rule_pack_id}/publish")
def publish_rule_pack(
    rule_pack_id: str,
    request: Request,
    user: UserRow = Depends(require_role("admin")),
):
    org = organization(request, user)
    result = get_operations().publish_rule_pack(
        organization_id=org.id, rule_pack_id=rule_pack_id, user=user
    )
    audit(request, "rule_pack.published", "rule_pack", rule_pack_id, user)
    return result


@router.post("/api/rule-packs/{rule_pack_id}/simulate")
def simulate_rule_pack(
    rule_pack_id: str,
    payload: RuleSimulationPayload,
    request: Request,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return get_operations().simulate_rule_pack(
        organization_id=org.id, rule_pack_id=rule_pack_id, input_data=payload.input
    )


@router.get("/api/reference-data")
def reference_data(
    request: Request,
    category: str | None = None,
    q: str | None = None,
    active_only: bool = True,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return {
        "items": get_operations().list_reference_data(
            organization_id=org.id,
            category=category,
            query=q,
            active_only=active_only,
        )
    }


@router.post("/api/reference-data", status_code=201)
def create_reference_data(
    payload: ReferenceDataPayload,
    request: Request,
    user: UserRow = Depends(require_role("admin")),
):
    org = organization(request, user)
    result = get_operations().create_reference_data(
        organization_id=org.id, user=user, payload=payload.model_dump()
    )
    audit(request, "reference_data.created", "reference_data", result["id"], user)
    return result


@router.get("/api/notifications")
def notifications(
    request: Request,
    unread_only: bool = False,
    user: UserRow = Depends(current_user),
):
    org = organization(request, user)
    return get_operations().list_notifications(
        organization_id=org.id, user_id=user.id, unread_only=unread_only
    )


@router.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str, request: Request, user: UserRow = Depends(current_user)
):
    org = organization(request, user)
    return get_operations().mark_notification_read(
        organization_id=org.id, user_id=user.id, notification_id=notification_id
    )


@router.post("/api/integrations/service-accounts", status_code=201)
def create_service_account(
    payload: ServiceAccountPayload, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().create_service_token(
        organization_id=org.id, payload=payload.model_dump()
    )
    audit(
        request,
        "integration.service_account_created",
        "service_account",
        result["service_account"]["id"],
        user,
    )
    return result


@router.get("/api/integrations/service-accounts")
def service_accounts(request: Request, user: UserRow = Depends(require_role("admin"))):
    org = organization(request, user)
    return {"items": get_operations().list_service_accounts(organization_id=org.id)}


@router.post("/api/integrations/service-accounts/{service_account_id}/revoke")
def revoke_service_account(
    service_account_id: str, request: Request, user: UserRow = Depends(require_role("admin"))
):
    org = organization(request, user)
    result = get_operations().revoke_service_account(
        organization_id=org.id, service_account_id=service_account_id
    )
    audit(
        request, "integration.service_account_revoked", "service_account", service_account_id, user
    )
    return result


@router.post("/api/integrations/service-accounts/{service_account_id}/rotate", status_code=201)
def rotate_service_account(
    service_account_id: str,
    request: Request,
    payload: ServiceAccountPayload | None = None,
    user: UserRow = Depends(require_role("admin")),
):
    org = organization(request, user)
    result = get_operations().rotate_service_token(
        organization_id=org.id,
        service_account_id=service_account_id,
        expires_at=payload.expires_at if payload else None,
    )
    audit(
        request, "integration.service_account_rotated", "service_account", service_account_id, user
    )
    return result


@router.post("/api/v1/shipments", status_code=201)
def inbound_shipment(
    payload: dict[str, Any],
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not authorization or not authorization.casefold().startswith("bearer "):
        raise OuturnError(
            "A bearer service token is required.", code="UNAUTHENTICATED", status_code=401
        )
    if not idempotency_key or len(idempotency_key) > 160:
        raise OuturnError(
            "Idempotency-Key is required.", code="VALIDATION_ERROR", status_code=422
        )
    required = {"internal_reference", "origin", "destination"}
    if not required.issubset(payload):
        raise OuturnError(
            "Shipment reference, origin, and destination are required.",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    raw_token = authorization[7:].strip()
    principal = get_operations().service_token_context(raw_token)
    principal.requires_scope("shipment.write")
    enforce_service_rate_limit(principal)
    org_id = principal.organization_id
    reservation = ApiIdempotencyRow(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        service_account_id=principal.service_account_id,
        idempotency_key=idempotency_key,
        status="PROCESSING",
        response_json=None,
        created_at=datetime.now(UTC),
    )
    with get_operations().session_factory() as session:
        existing = session.scalar(
            select(ApiIdempotencyRow).where(
                ApiIdempotencyRow.organization_id == org_id,
                ApiIdempotencyRow.service_account_id == principal.service_account_id,
                ApiIdempotencyRow.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.status == "SUCCEEDED" and existing.response_json:
                return json.loads(existing.response_json)
            raise OuturnError(
                "An earlier request with this Idempotency-Key is still processing.",
                code="IDEMPOTENCY_IN_PROGRESS",
                status_code=409,
            )
        session.add(reservation)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(ApiIdempotencyRow).where(
                    ApiIdempotencyRow.organization_id == org_id,
                    ApiIdempotencyRow.service_account_id == principal.service_account_id,
                    ApiIdempotencyRow.idempotency_key == idempotency_key,
                )
            )
            if existing and existing.status == "SUCCEEDED" and existing.response_json:
                return json.loads(existing.response_json)
            raise OuturnError(
                "An earlier request with this Idempotency-Key is still processing.",
                code="IDEMPOTENCY_IN_PROGRESS",
                status_code=409,
            ) from None
    from app.repositories.reconciliations import ReconciliationRepository

    try:
        shipment = ReconciliationRepository(get_settings().database_url).create_shipment(
            organization_id=org_id,
            payload=payload,
            actor=principal,
        )
    except Exception:
        with get_operations().session_factory() as session:
            row = session.get(ApiIdempotencyRow, reservation.id)
            if row:
                row.status = "FAILED"
                session.commit()
        raise
    with get_operations().session_factory() as session:
        session.add(
            DomainEventRow(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                event_type="api.shipment.accepted",
                entity_type="shipment",
                entity_id=shipment["id"],
                idempotency_key=idempotency_key,
                payload_json=json.dumps({"idempotency_key": idempotency_key}),
                created_at=datetime.now(UTC),
            )
        )
        row = session.get(ApiIdempotencyRow, reservation.id)
        if row:
            row.status = "SUCCEEDED"
            row.response_json = json.dumps(shipment, default=str)
        session.commit()
    from app.api.routes import get_repository

    get_repository().record_audit(
        "api.shipment.accepted",
        "shipment",
        entity_id=shipment["id"],
        actor=principal,
        organization_id=org_id,
        metadata={"idempotency_key": idempotency_key},
        request_id=request.state.request_id,
    )
    return shipment
