from datetime import UTC, datetime, timedelta

from conftest import login
from fastapi.testclient import TestClient

from app.main import app


def test_workspace_context_connections_and_service_account_lifecycle():
    client = login(TestClient(app))
    context = client.get("/api/workspace-context")
    assert context.status_code == 200, context.text
    assert context.json()["role"] == "admin"
    assert "*" in context.json()["permissions"]

    private_connection = client.post(
        "/api/integrations/connections",
        json={
            "name": "Private adapter",
            "type": "WMS",
            "configuration": {"base_url": "http://10.0.0.4"},
        },
    )
    assert private_connection.status_code == 422

    connection = client.post(
        "/api/integrations/connections",
        json={
            "name": "Warehouse adapter",
            "type": "WMS",
            "configuration": {"base_url": "https://example.com", "region": "ap-southeast-1"},
            "credential_reference": "secret/wms/current",
        },
    )
    assert connection.status_code == 201, connection.text
    connection_id = connection.json()["id"]
    assert "secret/wms" not in connection.text
    validated = client.post(f"/api/integrations/connections/{connection_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["checks"]["provider_adapter"] == "NOT_CONFIGURED"
    tested = client.post(f"/api/integrations/connections/{connection_id}/test")
    assert tested.status_code == 200
    assert tested.json()["provider_status"] == "NOT_CONFIGURED"
    assert client.post(f"/api/integrations/connections/{connection_id}/enable").status_code == 409
    rotated = client.post(
        f"/api/integrations/connections/{connection_id}/rotate",
        json={"credential_reference": "secret/wms/next"},
    )
    assert rotated.status_code == 200
    assert client.post(f"/api/integrations/connections/{connection_id}/disable").status_code == 200
    listed = client.get("/api/integrations/connections")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["credential_configured"] is True
    assert "secret/wms/next" not in listed.text

    created = client.post(
        "/api/integrations/service-accounts",
        json={
            "name": "Expiry partner",
            "scopes": ["shipment.write"],
            "expires_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    account_id = created.json()["service_account"]["id"]
    metadata = client.get("/api/integrations/service-accounts")
    assert metadata.status_code == 200
    assert token not in metadata.text
    rejected_rotation = client.post(
        f"/api/integrations/service-accounts/{account_id}/rotate",
        json={"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    )
    assert rejected_rotation.status_code == 422
    rotated_token = client.post(f"/api/integrations/service-accounts/{account_id}/rotate")
    assert rotated_token.status_code == 201
    assert rotated_token.json()["token"] != token
    assert client.post(f"/api/integrations/service-accounts/{account_id}/revoke").status_code == 200
    rejected = client.post(
        "/api/v1/shipments",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "revoked-key"},
        json={"internal_reference": "REV-1", "origin": "A", "destination": "B"},
    )
    assert rejected.status_code == 401


def test_webhook_lifecycle_retry_and_retention_legal_hold():
    client = login(TestClient(app))
    webhook = client.post(
        "/api/integrations/webhooks",
        json={"name": "Delivery callback", "endpoint": "https://example.com/events", "events": []},
    )
    assert webhook.status_code == 201, webhook.text
    subscription_id = webhook.json()["subscription"]["id"]
    assert webhook.json()["secret"]
    queued = client.post(f"/api/integrations/webhooks/{subscription_id}/test", json={})
    assert queued.status_code == 202
    delivery_id = queued.json()["delivery"]["id"]
    retried = client.post(f"/api/integrations/webhooks/deliveries/{delivery_id}/retry")
    assert retried.status_code == 202
    rotated = client.post(f"/api/integrations/webhooks/{subscription_id}/rotate")
    assert rotated.status_code == 200
    assert rotated.json()["secret"]
    assert client.post(f"/api/integrations/webhooks/{subscription_id}/disable").status_code == 200
    assert client.post(f"/api/integrations/webhooks/{subscription_id}/enable").status_code == 200

    saved = client.patch(
        "/api/settings/workspace",
        json={
            "values": {
                "retention": {
                    "audit_days": 30,
                    "document_days": 30,
                    "job_days": 7,
                    "webhook_days": 7,
                }
            }
        },
    )
    assert saved.status_code == 200, saved.text
    preview = client.post("/api/settings/retention/dry-run")
    assert preview.status_code == 200
    assert preview.json()["mutated"] is False
    shipment = client.post(
        "/api/shipments",
        json={"internal_reference": "HOLD-1", "origin": "AA", "destination": "BB"},
    )
    assert shipment.status_code == 201, shipment.text
    hold = client.post(
        f"/api/settings/retention/legal-holds/{shipment.json()['id']}",
        json={"active": True, "reason": "Open customer investigation"},
    )
    assert hold.status_code == 200
    held_preview = client.post("/api/settings/retention/dry-run")
    assert held_preview.json()["legal_holds"] == 1
    released = client.post(
        f"/api/settings/retention/legal-holds/{shipment.json()['id']}",
        json={"active": False, "reason": "Investigation closed"},
    )
    assert released.status_code == 200
    cleanup = client.post("/api/settings/retention/cleanup")
    assert cleanup.status_code == 200
    assert cleanup.json()["mutated"] is True
