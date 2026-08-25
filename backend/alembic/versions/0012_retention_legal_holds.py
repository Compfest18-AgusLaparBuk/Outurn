"""Add tenant-scoped legal holds for retention cleanup exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "0012_retention_legal_holds"
down_revision = "0011_policy_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "legal_holds" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "legal_holds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("shipment_id", sa.String(36), sa.ForeignKey("shipment_cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("organization_id", "shipment_id", name="uq_legal_hold_shipment"),
        )
        op.create_index("ix_legal_holds_organization_id", "legal_holds", ["organization_id"])
        op.create_index("ix_legal_holds_shipment_id", "legal_holds", ["shipment_id"])
        op.create_index("ix_legal_holds_active", "legal_holds", ["active"])
        op.create_index("ix_legal_holds_created_at", "legal_holds", ["created_at"])


def downgrade() -> None:
    if "legal_holds" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("legal_holds")
