from app.domain.models import (
    GeoClassification,
    GeographicValidation,
    Mismatch,
    MismatchType,
    ReconciliationStatus,
    RiskLevel,
    Severity,
)
from app.domain.risk import assess_risk


def geo(classification=GeoClassification.GEOGRAPHIC_MATCH):
    return GeographicValidation(classification=classification, message="test")


def mismatch(kind: MismatchType, severity=Severity.HIGH):
    return Mismatch(
        id="m-1",
        type=kind,
        severity=severity,
        field="items.quantity",
        explanation="Evidence differs.",
    )


def test_quantity_mismatch_is_deterministic_high_risk():
    result = assess_risk(
        [mismatch(MismatchType.QUANTITY_MISMATCH)],
        geo(),
        ReconciliationStatus.HOLD,
    )
    assert result.score == 35
    assert result.level == RiskLevel.HIGH
    assert result.contributors[0].points == 35


def test_geographic_mismatch_adds_fixed_contribution():
    result = assess_risk(
        [], geo(GeoClassification.DESTINATION_MISMATCH), ReconciliationStatus.HOLD
    )
    assert result.score == 20
    assert result.contributors[0].code == "DESTINATION_MISMATCH"
