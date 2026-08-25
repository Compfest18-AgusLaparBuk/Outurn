"""Add encrypted webhook delivery state and publish the first typed policy pack."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "0010_integrations_runtime"
down_revision = "0009_document_extraction_result"
branch_labels = None
depends_on = None


def _add_if_missing(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if column.name not in {item["name"] for item in inspector.get_columns(table)}:
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def upgrade() -> None:
    _add_if_missing("webhook_subscriptions", sa.Column("secret_ciphertext", sa.Text(), nullable=True))
    _add_if_missing("webhook_deliveries", sa.Column("event_id", sa.String(36), nullable=True))
    _add_if_missing(
        "webhook_deliveries", sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}")
    )
    _add_if_missing("webhook_deliveries", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))

    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("webhook_deliveries")}
    if "ix_webhook_deliveries_event_id" not in indexes:
        op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
    if "uq_webhook_delivery_subscription_event" not in indexes:
        op.create_index(
            "uq_webhook_delivery_subscription_event",
            "webhook_deliveries",
            ["subscription_id", "event_id"],
            unique=True,
        )

    # Seed one explicit immutable policy release for installations that do not
    # yet have a published pack. Existing tenant data remains untouched.
    from sqlalchemy.orm import Session

    from app.repositories.operations import RuleDefinitionRow, RulePackRow
    from app.repositories.reconciliations import UserRow

    session = Session(bind=op.get_bind())
    try:
        published = session.scalar(
            sa.select(RulePackRow.id).where(RulePackRow.status == "PUBLISHED").limit(1)
        )
        if published is None:
            user_id = session.scalar(sa.select(UserRow.id).order_by(UserRow.created_at.asc()).limit(1))
            pack_id = str(uuid4())
            now = datetime.now(UTC)
            session.add(
                RulePackRow(
                    id=pack_id,
                    organization_id=None,
                    name="GateGuard Core Assurance Policy",
                    version="2026.08.1",
                    status="PUBLISHED",
                    scope="GLOBAL",
                    effective_from=now,
                    effective_to=None,
                    created_by=user_id or "system",
                    published_by=user_id,
                    published_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            for rule_id, name, description, condition in (
                ("DOCS_REQUIRED", "Required shipment documents", "All active document requirements must have evidence.", {"check_type": "DOCUMENT_REQUIREMENTS"}),
                ("DG_COMPLETE", "Dangerous goods completeness", "Dangerous goods declarations require complete identifiers.", {"check_type": "DANGEROUS_GOODS"}),
                ("SCREENING_REVIEW", "Party screening disposition", "Missing or unresolved screening cannot authorize release.", {"check_type": "PARTY_SCREENING"}),
            ):
                session.add(
                    RuleDefinitionRow(
                        id=str(uuid4()),
                        rule_pack_id=pack_id,
                        rule_id=rule_id,
                        name=name,
                        description=description,
                        condition_json=json.dumps(condition, sort_keys=True),
                        active=True,
                        created_at=now,
                    )
                )
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("webhook_deliveries")}
    if "uq_webhook_delivery_subscription_event" in indexes:
        op.drop_index("uq_webhook_delivery_subscription_event", table_name="webhook_deliveries")
    if "ix_webhook_deliveries_event_id" in indexes:
        op.drop_index("ix_webhook_deliveries_event_id", table_name="webhook_deliveries")
    for table, column in (
        ("webhook_deliveries", "next_attempt_at"),
        ("webhook_deliveries", "payload_json"),
        ("webhook_deliveries", "event_id"),
        ("webhook_subscriptions", "secret_ciphertext"),
    ):
        if column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
