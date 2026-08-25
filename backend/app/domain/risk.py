from __future__ import annotations

from app.domain.models import (
    GeoClassification,
    GeographicValidation,
    Mismatch,
    MismatchType,
    ReconciliationStatus,
    RiskAssessment,
    RiskContributor,
    RiskLevel,
    Severity,
)

POINTS_BY_TYPE = {
    MismatchType.QUANTITY_MISMATCH: (35, "Quantity mismatch"),
    MismatchType.WRONG_SKU: (40, "SKU mismatch"),
    MismatchType.MISSING_ITEM: (30, "Missing line item"),
    MismatchType.WRONG_RECIPIENT: (30, "Recipient inconsistency"),
    MismatchType.WRONG_DESTINATION: (25, "Destination inconsistency"),
    MismatchType.WRONG_SENDER: (15, "Sender inconsistency"),
    MismatchType.DOCUMENT_ID_MISMATCH: (15, "Shipment reference mismatch"),
    MismatchType.WRONG_DOCUMENT_TYPE: (30, "Wrong document type"),
    MismatchType.TOTAL_MISMATCH: (15, "Document total mismatch"),
    MismatchType.POSSIBLE_TEXT_VARIATION: (7, "Entity or address ambiguity"),
    MismatchType.LOW_CONFIDENCE_EXTRACTION: (10, "Low extraction confidence"),
}


def assess_risk(
    mismatches: list[Mismatch],
    geographic: GeographicValidation,
    status: ReconciliationStatus,
) -> RiskAssessment:
    contributors: list[RiskContributor] = []
    for mismatch in mismatches:
        points, label = POINTS_BY_TYPE.get(
            mismatch.type,
            (
                10 if mismatch.severity in {Severity.HIGH, Severity.CRITICAL} else 5,
                "Evidence anomaly",
            ),
        )
        contributors.append(
            RiskContributor(
                code=mismatch.type.value,
                label=label,
                points=points,
                detail=mismatch.explanation,
            )
        )

    if geographic.classification == GeoClassification.DESTINATION_MISMATCH:
        contributors.append(
            RiskContributor(
                code="DESTINATION_MISMATCH",
                label="Geographic destination mismatch",
                points=20,
                detail=geographic.message,
            )
        )
    elif geographic.classification in {
        GeoClassification.NEARBY_REVIEW,
        GeoClassification.GEOCODING_UNCERTAIN,
    }:
        contributors.append(
            RiskContributor(
                code=geographic.classification.value,
                label="Destination verification review",
                points=10,
                detail=geographic.message,
            )
        )

    score = min(100, sum(item.points for item in contributors))
    if status == ReconciliationStatus.HOLD or score >= 75:
        level = RiskLevel.CRITICAL if score >= 75 else RiskLevel.HIGH
    elif status == ReconciliationStatus.REVIEW or score >= 40:
        level = RiskLevel.HIGH if score >= 50 else RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW
    return RiskAssessment(score=score, level=level, contributors=contributors)
