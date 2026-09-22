"""Operational Intelligence & Gamification Governance.

Revision ID: 20260921_0014
Revises: 20260921_0013
"""
from alembic import op
import sqlalchemy as sa
revision = "20260921_0014"
down_revision = "20260921_0013"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "operational_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(220), nullable=False),
        sa.Column("issue_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("action_url", sa.String(500), nullable=False, server_default="/admin/dashboard"),
        sa.Column("assignee_label", sa.String(160), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(160), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("fingerprint", name="uq_operational_issue_fingerprint"),
    )
    for c in ("fingerprint","issue_type","severity","entity_type","entity_id","status","last_seen_at"):
        op.create_index(f"ix_operational_issues_{c}", "operational_issues", [c])
    op.create_table(
        "gamification_rule_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_key", sa.String(180), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False, server_default="system"),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("new_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_label", sa.String(160), nullable=False, server_default="web"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for c in ("rule_key","entity_type","entity_id","field_name","effective_at","created_at"):
        op.create_index(f"ix_gamification_rule_versions_{c}", "gamification_rule_versions", [c])

def downgrade():
    op.drop_table("gamification_rule_versions")
    op.drop_table("operational_issues")
