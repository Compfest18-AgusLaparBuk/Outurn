import socket
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.auth.passwords import hash_password
from app.core.errors import GateGuardError
from app.repositories.operations import (
    DomainEventRow,
    OperationsRepository,
    OrganizationRow,
    ProcessingJobRow,
    WebhookDeliveryRow,
)
from app.repositories.reconciliations import ReconciliationRepository, ReviewTaskRow
from app.worker import assert_public_webhook_addresses


def _organization(operations: OperationsRepository, code: str) -> str:
    organization_id = str(uuid4())
    now = datetime.now(UTC)
    with operations.session_factory() as session:
        session.add(
            OrganizationRow(
                id=organization_id,
                name=f"{code} workspace",
                code=code,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return organization_id


def test_domain_event_outbox_is_tenant_scoped_and_idempotent(tmp_path):
    operations = OperationsRepository(f"sqlite:///{tmp_path / 'outbox.db'}")
    first_org = _organization(operations, "OUTBOX-A")
    second_org = _organization(operations, "OUTBOX-B")
    first = operations.create_webhook(
        organization_id=first_org,
        payload={"name": "A callback", "endpoint": "https://example.com/a", "events": []},
    )
    operations.create_webhook(
        organization_id=second_org,
        payload={"name": "B callback", "endpoint": "https://example.com/b", "events": []},
    )
    now = datetime.now(UTC)
    with operations.session_factory() as session:
        session.add(
            DomainEventRow(
                id=str(uuid4()),
                organization_id=first_org,
                event_type="shipment.updated",
                entity_type="shipment",
                entity_id=str(uuid4()),
                payload_json='{"state":"HOLD"}',
                created_at=now,
            )
        )
        session.commit()

    assert operations.enqueue_domain_event_deliveries() == 1
    assert operations.enqueue_domain_event_deliveries() == 0
    first_deliveries = operations.list_webhook_deliveries(
        organization_id=first_org, subscription_id=first["subscription"]["id"]
    )
    assert len(first_deliveries) == 1
    assert first_deliveries[0]["organization_id"] == first_org


def test_webhook_secret_and_configuration_values_are_not_returned(tmp_path):
    operations = OperationsRepository(f"sqlite:///{tmp_path / 'secrets.db'}")
    organization_id = _organization(operations, "SECRET-A")
    webhook = operations.create_webhook(
        organization_id=organization_id,
        payload={"name": "Secret callback", "endpoint": "https://example.com/events", "events": []},
    )
    listed = operations.list_webhooks(organization_id=organization_id)[0]
    assert webhook["secret"]
    assert "secret_hash" not in listed
    assert "secret_ciphertext" not in listed

    with pytest.raises(GateGuardError):
        operations.create_connection(
            organization_id=organization_id,
            user=SimpleNamespace(id=str(uuid4())),
            payload={
                "name": "Unsafe connection",
                "type": "WMS",
                "configuration": {"api_token": "should-not-be-stored"},
            },
        )


def test_webhook_dispatch_rejects_non_global_dns_answers(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        assert_public_webhook_addresses("https://callback.example.com/events")


def test_dead_lettered_webhook_job_marks_delivery_failed(tmp_path):
    operations = OperationsRepository(f"sqlite:///{tmp_path / 'dead-letter.db'}")
    organization_id = _organization(operations, "DEAD-LETTER-A")
    webhook = operations.create_webhook(
        organization_id=organization_id,
        payload={
            "name": "Dead-letter callback",
            "endpoint": "https://example.com/events",
            "events": [],
        },
    )
    queued = operations.queue_webhook_delivery(
        organization_id=organization_id,
        subscription_id=webhook["subscription"]["id"],
        event_type="webhook.test",
        payload={"source": "test"},
        allow_unlisted_test=True,
    )
    with operations.session_factory() as session:
        job = session.get(ProcessingJobRow, queued["job_id"])
        assert job is not None
        job.attempts = job.max_attempts
        session.commit()
    operations.finish_job(
        job_id=queued["job_id"],
        success=False,
        error_code="WORKER_HANDLER_FAILED",
        safe_error="Webhook delivery attempt failed safely.",
    )
    with operations.session_factory() as session:
        delivery = session.get(WebhookDeliveryRow, queued["delivery"]["id"])
        assert delivery is not None
        assert delivery.status == "FAILED"
        assert delivery.next_attempt_at is None


def test_review_policy_sla_is_applied_to_new_work_queue_tasks(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'policy.db'}"
    operations = OperationsRepository(database_url)
    organization_id = _organization(operations, "POLICY-A")
    reconciliation = ReconciliationRepository(database_url)
    user = reconciliation.create_user(
        email="policy@example.test",
        display_name="Policy reviewer",
        password_hash=hash_password("a secure policy password"),
        role="admin",
        organization_id=organization_id,
    )
    operations.save_settings(
        organization_id=organization_id,
        user=user,
        values={"review_policy": {"low_sla_hours": 2}},
    )
    shipment = reconciliation.create_shipment(
        organization_id=organization_id,
        actor=user,
        payload={
            "internal_reference": "POLICY-SHP-001",
            "origin": "Jakarta",
            "destination": "Bandung",
            "transport_mode": "Road",
        },
    )
    with operations.session_factory() as session:
        task = session.query(ReviewTaskRow).filter_by(shipment_id=shipment["id"]).one()
    assert task.due_at is not None
    assert 7100 <= (task.due_at - task.created_at).total_seconds() <= 7300
