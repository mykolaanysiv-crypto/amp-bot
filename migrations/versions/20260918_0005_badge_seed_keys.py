"""Add stable seed keys so built-in badges can be deleted permanently.

Revision ID: 20260918_0005
Revises: 20260918_0004
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260918_0005"
down_revision: Union[str, None] = "20260918_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "badges" not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns("badges")}
    if "seed_key" not in cols:
        op.add_column("badges", sa.Column("seed_key", sa.String(length=120), nullable=True))

    # Backfill stable identifiers for all badges seeded by AMP. Visible names may
    # later be edited without losing the seed identity.
    core = [
        ("core:xp_transactions:1", "xp_transactions", 1),
        ("core:xp_transactions:10", "xp_transactions", 10),
        ("core:volunteer_hours:50", "volunteer_hours", 50),
        ("core:volunteer_hours:100", "volunteer_hours", 100),
        ("core:referrals:3", "referrals", 3),
        ("core:quests:5", "quests", 5),
        ("core:xp_total:300", "xp_total", 300),
        ("core:xp_total:800", "xp_total", 800),
        ("core:xp_total:1200", "xp_total", 1200),
    ]
    for seed_key, criteria_type, criteria_value in core:
        bind.execute(
            sa.text(
                "UPDATE badges SET seed_key=:seed_key "
                "WHERE seed_key IS NULL AND criteria_type=:criteria_type "
                "AND criteria_value=:criteria_value AND automatic=TRUE AND badge_type='general'"
            ),
            {"seed_key": seed_key, "criteria_type": criteria_type, "criteria_value": criteria_value},
        )

    donation = [
        ("donation:donation_first:5000:general", "donation_first", 5000, "general"),
        ("donation:donation_single:20000:general", "donation_single", 20000, "general"),
        ("donation:donation_single:50000:general", "donation_single", 50000, "general"),
        ("donation:donation_single:100000:general", "donation_single", 100000, "general"),
        ("donation:donation_total_over:200000:general", "donation_total_over", 200000, "general"),
        ("donation:donation_total_over:500000:ambassador", "donation_total_over", 500000, "ambassador"),
    ]
    for seed_key, criteria_type, criteria_value, badge_type in donation:
        bind.execute(
            sa.text(
                "UPDATE badges SET seed_key=:seed_key "
                "WHERE seed_key IS NULL AND criteria_type=:criteria_type "
                "AND criteria_value=:criteria_value AND badge_type=:badge_type"
            ),
            {"seed_key": seed_key, "criteria_type": criteria_type, "criteria_value": criteria_value, "badge_type": badge_type},
        )

    manual = [
        ("manual:clean-start", "Чистий старт"),
        ("manual:amp-voice", "Голос АМП"),
        ("manual:content-maker", "Контент-мейкер"),
        ("manual:networker", "Нетворкер"),
        ("manual:idea-maker", "Ідейник"),
        ("manual:mentor", "Ментор"),
        ("manual:change-maker", "Запускаю зміни"),
    ]
    for seed_key, name in manual:
        bind.execute(
            sa.text("UPDATE badges SET seed_key=:seed_key WHERE seed_key IS NULL AND name=:name"),
            {"seed_key": seed_key, "name": name},
        )

    indexes = {i["name"] for i in inspect(bind).get_indexes("badges")}
    if "ux_badges_seed_key" not in indexes:
        op.create_index("ux_badges_seed_key", "badges", ["seed_key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "badges" not in set(inspector.get_table_names()):
        return
    indexes = {i["name"] for i in inspector.get_indexes("badges")}
    if "ux_badges_seed_key" in indexes:
        op.drop_index("ux_badges_seed_key", table_name="badges")
    cols = {c["name"] for c in inspect(bind).get_columns("badges")}
    if "seed_key" in cols:
        op.drop_column("badges", "seed_key")
