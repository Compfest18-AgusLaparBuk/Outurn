from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.models import RiskLevel, ShipmentStatus


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    level: RiskLevel
    factors: list[dict[str, Any]]


def policy_risk_config(rule_definitions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Read risk scoring from the immutable published rule-pack.

    Risk is deliberately data-driven.  The evaluator has no product-specific
    weight table; a missing policy rule is treated as an unsafe configuration
    so a workspace cannot accidentally downgrade an unknown blocker.
    """
    weights: dict[str, int] = {}
    thresholds: dict[str, int] = {}
    for definition in rule_definitions:
        condition = definition.get("condition", definition.get("condition_json", {}))
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                condition = {}
        if not isinstance(condition, Mapping):
            continue
        factor = condition.get("risk_factor")
        if factor:
            try:
                weight = int(condition.get("weight", 0))
            except (TypeError, ValueError):
                weight = 0
            if 0 <= weight <= 100:
                weights[str(factor)] = weight
        threshold = condition.get("risk_level")
        if threshold:
            try:
                value = int(condition.get("threshold"))
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 100:
                thresholds[str(threshold).upper()] = value
    return {"weights": weights, "thresholds": thresholds}


def calculate_risk(
    active_factors: list[tuple[str, str]],
    policy: Mapping[str, Any] | None = None,
) -> RiskAssessment:
    """Calculate a transparent, deterministic risk score from a published policy."""
    config = policy or {}
    weights = config.get("weights", {}) if isinstance(config, Mapping) else {}
    thresholds = config.get("thresholds", {}) if isinstance(config, Mapping) else {}
    factors: list[dict[str, Any]] = []
    score = 0
    for code, reason in active_factors:
        raw_weight = weights.get(code) if isinstance(weights, Mapping) else None
        # Unknown findings remain maximally conservative until a published
        # policy explicitly assigns their operational weight.
        weight = int(raw_weight) if raw_weight is not None else 100
        score += weight
        factors.append({"code": code, "reason": reason, "weight": weight})
    bounded = min(score, 100)
    critical = int(thresholds.get("CRITICAL", 75)) if isinstance(thresholds, Mapping) else 75
    high = int(thresholds.get("HIGH", 50)) if isinstance(thresholds, Mapping) else 50
    medium = int(thresholds.get("MEDIUM", 25)) if isinstance(thresholds, Mapping) else 25
    if bounded >= critical:
        level = RiskLevel.CRITICAL
    elif bounded >= high:
        level = RiskLevel.HIGH
    elif bounded >= medium:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW
    return RiskAssessment(score=float(bounded), level=level, factors=factors)


SHIPMENT_TRANSITIONS: dict[str, set[str]] = {
    ShipmentStatus.DRAFT.value: {ShipmentStatus.DOCUMENTS_REQUIRED.value},
    ShipmentStatus.DOCUMENTS_REQUIRED.value: {
        ShipmentStatus.READY_FOR_ASSESSMENT.value,
        ShipmentStatus.ASSESSING.value,
    },
    ShipmentStatus.READY_FOR_ASSESSMENT.value: {ShipmentStatus.ASSESSING.value},
    ShipmentStatus.ASSESSING.value: {
        ShipmentStatus.REVIEW_REQUIRED.value,
        ShipmentStatus.HOLD.value,
    },
    ShipmentStatus.REVIEW_REQUIRED.value: {
        ShipmentStatus.ASSESSING.value,
        ShipmentStatus.HOLD.value,
    },
    ShipmentStatus.HOLD.value: {
        ShipmentStatus.REVIEW_REQUIRED.value,
        ShipmentStatus.ASSESSING.value,
    },
    # Pending and authorization transitions are repository-internal: they require a
    # persisted release decision and a distinct second approver, respectively.
    ShipmentStatus.RELEASE_PENDING_APPROVAL.value: {ShipmentStatus.RELEASE_INVALIDATED.value},
    ShipmentStatus.RELEASE_AUTHORIZED.value: {
        ShipmentStatus.DISPATCHED.value,
        ShipmentStatus.RELEASE_INVALIDATED.value,
    },
    ShipmentStatus.RELEASE_INVALIDATED.value: {
        ShipmentStatus.REVIEW_REQUIRED.value,
        ShipmentStatus.HOLD.value,
    },
    ShipmentStatus.DISPATCHED.value: {ShipmentStatus.CLOSED.value},
    ShipmentStatus.CLOSED.value: set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in SHIPMENT_TRANSITIONS.get(current, set())
