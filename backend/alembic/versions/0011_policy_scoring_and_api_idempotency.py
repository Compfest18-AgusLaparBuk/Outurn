"""Make policy scoring data-driven and reserve external API idempotency keys."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0011_policy_scoring"
down_revision = "0010_integrations_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    domain_columns = {item["name"] for item in inspector.get_columns("domain_events")}
    if "idempotency_key" not in domain_columns:
        with op.batch_alter_table("domain_events") as batch:
            batch.add_column(sa.Column("idempotency_key", sa.String(160), nullable=True))
    domain_indexes = {item["name"] for item in inspector.get_indexes("domain_events")}
    if "ix_domain_events_idempotency_key" not in domain_indexes:
        op.create_index("ix_domain_events_idempotency_key", "domain_events", ["idempotency_key"])
    if "uq_domain_event_idempotency" not in domain_indexes:
        op.create_index(
            "uq_domain_event_idempotency",
            "domain_events",
            ["organization_id", "event_type", "idempotency_key"],
            unique=True,
        )

    if "api_idempotency_keys" not in inspector.get_table_names():
        op.create_table(
            "api_idempotency_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("service_account_id", sa.String(36), sa.ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="PROCESSING"),
            sa.Column("response_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "service_account_id", "idempotency_key", name="uq_api_idempotency_scope"),
        )
        op.create_index("ix_api_idempotency_keys_organization_id", "api_idempotency_keys", ["organization_id"])
        op.create_index("ix_api_idempotency_keys_service_account_id", "api_idempotency_keys", ["service_account_id"])
        op.create_index("ix_api_idempotency_keys_created_at", "api_idempotency_keys", ["created_at"])

    from sqlalchemy.orm import Session
    from app.repositories.operations import RuleDefinitionRow, RulePackRow

    session = Session(bind=op.get_bind())
    try:
        pack = session.scalar(
            sa.select(RulePackRow)
            .where(RulePackRow.organization_id.is_(None), RulePackRow.status == "PUBLISHED")
            .order_by(RulePackRow.published_at.desc())
        )
        if pack:
            existing = list(session.scalars(sa.select(RuleDefinitionRow).where(RuleDefinitionRow.rule_pack_id == pack.id)))
            factors = {
                json.loads(row.condition_json or "{}").get("risk_factor")
                for row in existing
            }
            now = datetime.now(UTC)
            definitions = (
                ("RISK_BLOCKING_ASSURANCE", "Risk weight: blocking assurance", "BLOCKING_ASSURANCE", 40),
                ("RISK_MISSING_DOCUMENT", "Risk weight: missing document", "MISSING_REQUIRED_DOCUMENT", 25),
                ("RISK_HIGH_EXCEPTION", "Risk weight: high exception", "HIGH_CRITICAL_EXCEPTION", 30),
                ("RISK_DANGEROUS_GOODS", "Risk weight: dangerous goods", "DANGEROUS_GOODS_INCOMPLETE", 20),
            )
            for rule_id, name, factor, weight in definitions:
                if factor in factors:
                    continue
                session.add(RuleDefinitionRow(
                    id=str(uuid4()), rule_pack_id=pack.id, rule_id=rule_id, name=name,
                    description="Published policy scoring input.",
                    condition_json=json.dumps({"risk_factor": factor, "weight": weight}, sort_keys=True),
                    active=True, created_at=now,
                ))
            levels = (("MEDIUM", 25), ("HIGH", 50), ("CRITICAL", 75))
            existing_levels = {
                json.loads(row.condition_json or "{}").get("risk_level")
                for row in existing
            }
            for level, threshold in levels:
                if level in existing_levels:
                    continue
                session.add(RuleDefinitionRow(
                    id=str(uuid4()), rule_pack_id=pack.id, rule_id=f"RISK_THRESHOLD_{level}",
                    name=f"Risk threshold: {level.lower()}", description="Published policy threshold.",
                    condition_json=json.dumps({"risk_level": level, "threshold": threshold}, sort_keys=True),
                    active=True, created_at=now,
                ))
        session.commit()
    finally:
        session.close()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "api_idempotency_keys" in inspector.get_table_names():
        op.drop_table("api_idempotency_keys")
    indexes = {item["name"] for item in inspector.get_indexes("domain_events")}
    if "uq_domain_event_idempotency" in indexes:
        op.drop_index("uq_domain_event_idempotency", table_name="domain_events")
    if "ix_domain_events_idempotency_key" in indexes:
        op.drop_index("ix_domain_events_idempotency_key", table_name="domain_events")
    if "idempotency_key" in {item["name"] for item in sa.inspect(op.get_bind()).get_columns("domain_events")}:
        with op.batch_alter_table("domain_events") as batch:
            batch.drop_column("idempotency_key")
