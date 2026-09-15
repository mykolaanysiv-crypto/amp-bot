"""v1.11.1 production schema baseline.

Revision ID: 20260915_0001
Revises: None

This is intentionally a no-op baseline. v1.12.0 adopts Alembic gradually:
legacy installations are first brought to the v1.11.1-compatible schema by the
existing idempotent compatibility bootstrap, then stamped at this revision.
All new schema changes after the baseline must be expressed as Alembic
revisions instead of being appended to the legacy custom upgrader.
"""
from typing import Sequence, Union

revision: str = "20260915_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
