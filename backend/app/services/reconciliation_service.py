from __future__ import annotations

import asyncio
import time
import uuid

from app.core.config import Settings
from app.domain.explanation import explain_findings
from app.domain.models import (
    AuditState,
    DocumentType,
    ReconciliationResult,
    ReconciliationStatus,
    ShipmentAssuranceContext,
)
from app.domain.reconciliation import reconcile
from app.domain.risk import assess_risk
from app.repositories.reconciliations import ReconciliationRepository
from app.services.extraction import ExtractionRouter
from app.services.file_validation import SafeUpload
from app.services.geocoding import NominatimGeocoder


class ReconciliationService:
    def __init__(
        self,
        settings: Settings,
        repository: ReconciliationRepository,
        extractor: ExtractionRouter,
        geocoder: NominatimGeocoder,
    ):
        self.settings = settings
        self.repository = repository
        self.extractor = extractor
        self.geocoder = geocoder

    async def reconcile_uploads(
        self,
        uploads: dict[DocumentType, SafeUpload],
        *,
        organization_id: str,
        context: ShipmentAssuranceContext | None = None,
    ) -> ReconciliationResult:
        started = time.perf_counter()
        ordered = list(uploads.items())
        extracted = await asyncio.gather(
            *(self.extractor.extract(upload, dtype) for dtype, upload in ordered)
        )
        documents = {
            dtype: document for (dtype, _), document in zip(ordered, extracted, strict=True)
        }
        status, reason, action, mismatches = reconcile(
            documents,
            confidence_threshold=self.settings.critical_confidence_threshold,
        )
        geographic = await self.geocoder.validate(
            origin=context.origin if context else None,
            expected_destination=context.expected_destination if context else None,
            document_destinations={
                dtype: document.destination.value
                for dtype, document in documents.items()
                if document.destination.value is not None
            },
        )
        if geographic.classification.value == "DESTINATION_MISMATCH":
            status = ReconciliationStatus.HOLD
            reason = "A material geographic destination conflict was detected."
            action = "Stop dispatch and verify the destination before release."
        elif geographic.classification.value in {"NEARBY_REVIEW", "GEOCODING_UNCERTAIN"}:
            if status == ReconciliationStatus.CLEAR:
                status = ReconciliationStatus.REVIEW
                reason = (
                    "Document fields are consistent, but destination verification "
                    "needs review."
                )
                action = "Confirm the operational destination and rerun the check before dispatch."
        risk = assess_risk(mismatches, geographic, status)
        explanation = explain_findings(mismatches, geographic)
        result = ReconciliationResult(
            session_id=str(uuid.uuid4()),
            status=status,
            reason=reason,
            recommended_action=action,
            documents=documents,
            mismatches=mismatches,
            audit=AuditState(system_decision=status),
            processing_ms=int((time.perf_counter() - started) * 1000),
            context=context,
            geographic=geographic,
            risk=risk,
            explanation=explanation,
        )
        return self.repository.save(result, organization_id=organization_id)
