"""Finalize Alembic ownership of production schema/runtime migrations.

Revision ID: 20260920_0009
Revises: 20260920_0008

No model columns are added by this release. The revision owns the last durable
legacy data backfill that previously ran from Database.init(): consolidation of
notification_deliveries into the canonical notifications outbox.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260920_0009"
down_revision: Union[str, None] = "20260920_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if not {"notification_deliveries", "notifications", "users"}.issubset(tables):
        return

    # Idempotent durable-outbox consolidation. This used to run at every
    # application startup; v1.17.1 makes it a one-time Alembic-owned backfill.
    bind.execute(sa.text("""
        INSERT INTO notifications (
            dedupe_key, recipient_user_id, recipient_tg_id, type, title, body,
            entity_type, scheduled_at, sent_at, status, error, retry_count,
            max_attempts, last_attempt_at, parse_mode, button_text, callback_data,
            created_at, updated_at
        )
        SELECT
            COALESCE(nd.dedupe_key, 'legacy_notification_delivery:' || nd.id),
            u.id,
            nd.recipient_tg_id,
            CASE
                WHEN lower(COALESCE(nd.source,'')) LIKE '%broadcast%' THEN 'broadcast'
                WHEN lower(COALESCE(nd.source,'')) LIKE '%event%'
                  OR lower(COALESCE(nd.source,'')) LIKE '%attendance%'
                  OR lower(COALESCE(nd.source,'')) LIKE '%waitlist%'
                  OR lower(COALESCE(nd.source,'')) LIKE '%feedback%' THEN 'event'
                WHEN lower(COALESCE(nd.source,'')) LIKE '%case%'
                  OR lower(COALESCE(nd.source,'')) LIKE '%request%' THEN 'case'
                WHEN lower(COALESCE(nd.source,'')) LIKE '%streak%' THEN 'streak'
                WHEN lower(COALESCE(nd.source,'')) LIKE '%survey%' THEN 'survey'
                ELSE 'system'
            END,
            '', nd.message_text, nd.source,
            COALESCE(nd.next_retry_at, nd.created_at, CURRENT_TIMESTAMP), nd.sent_at,
            CASE WHEN nd.status='pending' THEN 'queued' ELSE nd.status END,
            COALESCE(nd.last_error,''), COALESCE(nd.attempt_count,0), COALESCE(nd.max_attempts,4),
            nd.last_attempt_at, nd.parse_mode, nd.button_text, nd.callback_data,
            COALESCE(nd.created_at,CURRENT_TIMESTAMP), COALESCE(nd.updated_at,CURRENT_TIMESTAMP)
        FROM notification_deliveries nd
        LEFT JOIN users u ON u.tg_id = nd.recipient_tg_id
        WHERE NOT EXISTS (
            SELECT 1 FROM notifications n
            WHERE n.dedupe_key = COALESCE(nd.dedupe_key, 'legacy_notification_delivery:' || nd.id)
        )
    """))


def downgrade() -> None:
    # Data copied into the canonical outbox may have been processed after the
    # upgrade. Deleting it on downgrade would be destructive, so the adoption
    # revision intentionally has a data-safe no-op downgrade.
    pass
