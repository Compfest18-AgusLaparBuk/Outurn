from uuid import uuid4

from conftest import login
from fastapi.testclient import TestClient

from app.main import app


def test_operations_surface_reads_and_mutations_are_backend_backed():
    client = login(TestClient(app))
    reference = f"SURFACE-{uuid4().hex[:8].upper()}"
    created = client.post(
        "/api/shipments",
        json={
            "internal_reference": reference,
            "external_reference": "PO-SURFACE",
            "origin": "Jakarta",
            "destination": "Singapore",
            "transport_mode": "Sea",
        },
    )
    assert created.status_code == 201, created.text
    shipment_id = created.json()["id"]

    for path in (
        "/api/organizations",
        "/api/workspace-context",
        "/api/shipments",
        "/api/requirements",
        "/api/assurance",
        "/api/exceptions",
        "/api/releases",
        "/api/screening",
        "/api/dangerous-goods",
        "/api/integrations/jobs",
        "/api/integrations/connections",
        "/api/integrations/webhooks",
        "/api/settings/workspace",
        "/api/reference-data",
        "/api/notifications",
        "/api/analytics/summary?days=7",
        "/api/analytics/timeseries?days=7",
        "/api/observability",
        "/api/recents",
        "/api/runtime",
        "/api/monitoring",
        "/api/audit",
        "/api/users",
        "/api/rule-packs",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.text}"

    assert client.get(f"/api/shipments/{shipment_id}").status_code == 200
    assert client.get(f"/api/shipments/{shipment_id}/workspace").status_code == 200
    gate = client.get(f"/api/shipments/{shipment_id}/release-gate")
    assert gate.status_code == 200, gate.text
    assert {"blockers", "requirements", "latest_checks", "evidence_hash"}.issubset(gate.json())

    recent = client.post(
        "/api/recents",
        json={
            "object_type": "shipment",
            "object_id": shipment_id,
            "label": reference,
            "href": f"/shipments/{shipment_id}",
        },
    )
    assert recent.status_code == 200, recent.text
    assert client.get(f"/api/search?q={reference}").status_code == 200

    party = client.post(
        "/api/parties",
        json={
            "legal_name": "Surface Test Carrier",
            "country_code": "ID",
            "shipment_id": shipment_id,
            "role": "CARRIER",
        },
    )
    assert party.status_code == 201, party.text
    assert client.get("/api/parties?q=Surface").status_code == 200

    item = client.post(
        "/api/items",
        json={
            "shipment_id": shipment_id,
            "line_number": 1,
            "description": "Controlled surface sample",
            "quantity": 2,
            "dangerous_goods": True,
        },
    )
    assert item.status_code == 201, item.text
    assert client.post("/api/products", json=item.json() | {"line_number": 2}).status_code == 201
    assert client.get("/api/items?q=Controlled").status_code == 200
    assert client.get("/api/products?q=Controlled").status_code == 200
    dangerous = client.get("/api/dangerous-goods")
    assert dangerous.status_code == 200 and dangerous.json()["items"]

    transport = client.post(
        "/api/transport",
        json={
            "shipment_id": shipment_id,
            "sequence": 1,
            "mode": "Sea",
            "origin": "Jakarta",
            "destination": "Singapore",
        },
    )
    assert transport.status_code == 201, transport.text
    assert client.get(f"/api/transport?shipment_id={shipment_id}").status_code == 200

    assert client.get("/api/documents").status_code == 200
    rejected_metadata = client.post(
        "/api/documents",
        json={
            "shipment_id": shipment_id,
            "document_type": "INVOICE",
            "filename": "metadata.pdf",
        },
    )
    assert rejected_metadata.status_code == 410

    assessed = client.post(f"/api/shipments/{shipment_id}/assess")
    assert assessed.status_code == 202, assessed.text
    assert client.get(f"/api/shipments/{shipment_id}/assess").status_code == 405
    assert client.post(f"/api/shipments/{shipment_id}/screening").status_code == 202
    assert client.get(f"/api/shipments/{shipment_id}/trusted-reference").status_code == 200

    trusted = client.put(
        f"/api/shipments/{shipment_id}/trusted-reference",
        json={"shipment_reference": "different-reference", "expected_destination": "Singapore"},
    )
    assert trusted.status_code == 200, trusted.text
    assert client.get(f"/api/shipments/{shipment_id}/trusted-reference").status_code == 200

    packs = client.get("/api/rule-packs").json()["items"]
    assert packs
    pack_id = packs[0]["id"]
    assert client.get(f"/api/rule-packs/{pack_id}").status_code == 200
    simulated = client.post(f"/api/rule-packs/{pack_id}/simulate", json={"input": {}})
    assert simulated.status_code == 200, simulated.text

    settings = client.patch(
        "/api/settings/workspace",
        json={"values": {"review_policy": {"low_sla_hours": 48}}},
    )
    assert settings.status_code == 200, settings.text
    assert client.post("/api/settings/retention/dry-run").status_code == 200
