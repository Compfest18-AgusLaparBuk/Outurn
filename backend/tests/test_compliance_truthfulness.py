from conftest import login
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.operations import get_operations
from app.main import app
from app.repositories.operations import AssuranceCheckRow


def _shipment(client: TestClient, reference: str) -> str:
    response = client.post(
        "/api/shipments",
        json={
            "internal_reference": reference,
            "origin": "Jakarta",
            "destination": "Bandung",
            "transport_mode": "Road",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_unconfigured_screening_blocks_release_with_review_evidence():
    client = login(TestClient(app))
    shipment_id = _shipment(client, "SCREENING-TRUTH-001")
    party = client.post(
        "/api/parties",
        json={
            "legal_name": "Truthful Screening Party",
            "shipment_id": shipment_id,
            "role": "CONSIGNEE",
        },
    )
    assert party.status_code == 201, party.text

    response = client.post(f"/api/shipments/{shipment_id}/screening")
    assert response.status_code == 202, response.text
    assert response.json()["result"] == "NOT_CONFIGURED"

    operations = get_operations()
    with operations.session_factory() as session:
        check = session.scalar(
            select(AssuranceCheckRow)
            .where(
                AssuranceCheckRow.shipment_id == shipment_id,
                AssuranceCheckRow.check_type == "PARTY_SCREENING",
            )
            .order_by(AssuranceCheckRow.created_at.desc())
        )
    assert check is not None
    assert check.status == "REVIEW"
    assert check.severity == "HIGH"
    assert "manual disposition" in check.summary.casefold()


def test_webhook_configuration_queues_real_delivery_capability():
    client = login(TestClient(app))
    created = client.post(
        "/api/integrations/webhooks",
        json={
            "name": "Truthful callback",
            "endpoint": "https://example.invalid/gateguard-events",
            "events": ["shipment.updated"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["subscription"]["delivery_capability"] == "QUEUED_DELIVERY"

    listed = client.get("/api/integrations/webhooks")
    assert listed.status_code == 200, listed.text
    assert any(
        item["delivery_capability"] == "QUEUED_DELIVERY" for item in listed.json()["items"]
    )
    listed_item = next(
        item for item in listed.json()["items"] if item["name"] == "Truthful callback"
    )
    assert "secret_hash" not in listed_item
    assert "secret_ciphertext" not in listed_item

    test_delivery = client.post(
        f"/api/integrations/webhooks/{listed_item['id']}/test",
        json={"payload": {"fixture": "truthfulness"}},
    )
    assert test_delivery.status_code == 202, test_delivery.text
    assert test_delivery.json()["delivery"]["status"] == "QUEUED"
    deliveries = client.get(
        f"/api/integrations/webhooks/{listed_item['id']}/deliveries"
    )
    assert deliveries.status_code == 200, deliveries.text
    assert deliveries.json()["items"][0]["event_type"] == "webhook.test"
    assert "payload_json" not in deliveries.json()["items"][0]

    observability = client.get("/api/observability")
    assert observability.status_code == 200, observability.text
    assert observability.json()["webhook"] == "configured_queued"


def test_incomplete_dangerous_goods_forces_hold_after_assessment():
    from app.api.routes import get_repository

    client = login(TestClient(app))
    shipment_id = _shipment(client, "DG-TRUTH-001")
    item = client.post(
        "/api/items",
        json={
            "shipment_id": shipment_id,
            "line_number": 1,
            "description": "Lithium battery cells",
            "quantity": 4,
            "dangerous_goods": True,
            "un_number": "UN3480",
        },
    )
    assert item.status_code == 201, item.text

    workspace = client.get(f"/api/shipments/{shipment_id}/workspace")
    assert workspace.status_code == 200, workspace.text
    organization_id = workspace.json()["shipment"]["organization_id"]
    get_operations().complete_assessment(
        organization_id=organization_id,
        shipment_id=shipment_id,
    )

    shipment = get_repository().get_shipment(shipment_id, organization_id=organization_id)
    assert shipment["status"] == "HOLD"
    assert shipment["risk_level"] in {"HIGH", "CRITICAL"}
