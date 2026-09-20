"""Alembic bootstrap baseline for AMP schema.

Revision ID: 20260915_0001
Revises: None

v1.17.1 freezes the current production schema bootstrap inside Alembic.
Application startup no longer performs ORM metadata schema creation or a legacy
custom upgrader. Existing Alembic-managed production databases do not rerun
this revision; fresh databases are created entirely through the migration chain.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260915_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names()) - {"alembic_version"}
    if existing:
        # Existing production schemas were already adopted by Alembic in v1.12.x.
        # Never attempt an implicit create/alter path over live tables here.
        return

    op.create_table('activity_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('instructions', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('hours_reward', sa.Float(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('badges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('icon', sa.String(length=16), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('criteria_type', sa.String(length=64), nullable=True),
        sa.Column('criteria_value', sa.Integer(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('automatic', sa.Boolean(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('badge_type', sa.String(length=24), nullable=False),
        sa.Column('seed_key', sa.String(length=120), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('seed_key'),
    )

    op.create_table('broadcast_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_by_label', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('donation_jar_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jar_account_id', sa.String(length=120), nullable=True),
        sa.Column('send_id', sa.String(length=120), nullable=True),
        sa.Column('title', sa.String(length=180), nullable=True),
        sa.Column('balance_kop', sa.BigInteger(), nullable=False),
        sa.Column('goal_kop', sa.BigInteger(), nullable=False),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('donation_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=220), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('amount_spent_kop', sa.BigInteger(), nullable=False),
        sa.Column('spent_at', sa.DateTime(), nullable=True),
        sa.Column('document_path', sa.String(length=500), nullable=True),
        sa.Column('document_name', sa.String(length=255), nullable=True),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('giveaways',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('participation_mode', sa.String(length=24), nullable=False),
        sa.Column('task_text', sa.Text(), nullable=False),
        sa.Column('audience_type', sa.String(length=24), nullable=False),
        sa.Column('audience_value', sa.Text(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('created_by_label', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('drawn_at', sa.DateTime(), nullable=True),
        sa.Column('draw_seed', sa.String(length=128), nullable=True),
        sa.Column('draw_algorithm', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('media_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=80), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('notification_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=220), nullable=True),
        sa.Column('source', sa.String(length=80), nullable=False),
        sa.Column('recipient_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('parse_mode', sa.String(length=24), nullable=True),
        sa.Column('button_text', sa.String(length=120), nullable=True),
        sa.Column('callback_data', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('opportunities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('kind', sa.String(length=80), nullable=False),
        sa.Column('direction', sa.String(length=100), nullable=False),
        sa.Column('format', sa.String(length=80), nullable=False),
        sa.Column('age_min', sa.Integer(), nullable=True),
        sa.Column('age_max', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('deadline', sa.DateTime(), nullable=True),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('target_settlements', sa.Text(), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('rewards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('min_xp', sa.Integer(), nullable=False),
        sa.Column('stock', sa.Integer(), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('reward_type', sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('scheduled_jobs',
        sa.Column('job_name', sa.String(length=120), nullable=False),
        sa.Column('locked_at', sa.DateTime(), nullable=True),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('locked_by', sa.String(length=180), nullable=True),
        sa.Column('last_started_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=False),
        sa.Column('run_count', sa.Integer(), nullable=False),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('job_name'),
    )

    op.create_table('seasons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('starts_at', sa.Date(), nullable=False),
        sa.Column('ends_at', sa.Date(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finalized_at', sa.DateTime(), nullable=True),
        sa.Column('history_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table('settlement_references',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_name', sa.String(length=120), nullable=False),
        sa.Column('aliases_json', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('system_settings',
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )

    op.create_table('teams',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=140), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tg_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=True),
        sa.Column('full_name', sa.String(length=160), nullable=False),
        sa.Column('first_name', sa.String(length=80), nullable=True),
        sa.Column('last_name', sa.String(length=80), nullable=True),
        sa.Column('email', sa.String(length=160), nullable=True),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('settlement', sa.String(length=120), nullable=True),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('gender', sa.String(length=24), nullable=True),
        sa.Column('vulnerability_categories', sa.Text(), nullable=True),
        sa.Column('media_consent', sa.Boolean(), nullable=True),
        sa.Column('media_consent_status', sa.String(length=24), nullable=False),
        sa.Column('media_consent_version', sa.String(length=32), nullable=True),
        sa.Column('media_consent_recorded_at', sa.DateTime(), nullable=True),
        sa.Column('privacy_notice_version', sa.String(length=32), nullable=True),
        sa.Column('privacy_acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('birthday_reward_year', sa.Integer(), nullable=True),
        sa.Column('blocked_until', sa.DateTime(), nullable=True),
        sa.Column('block_reason', sa.Text(), nullable=True),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('parental_consent_required', sa.Boolean(), nullable=False),
        sa.Column('parental_consent_confirmed', sa.Boolean(), nullable=False),
        sa.Column('parental_consent_status', sa.String(length=24), nullable=False),
        sa.Column('parental_consent_received_at', sa.DateTime(), nullable=True),
        sa.Column('parental_consent_file_path', sa.String(length=500), nullable=True),
        sa.Column('leaderboard_opt_in', sa.Boolean(), nullable=False),
        sa.Column('volunteer_hours', sa.Float(), nullable=False),
        sa.Column('wallet_xp', sa.Integer(), nullable=False),
        sa.Column('public_token', sa.String(length=64), nullable=True),
        sa.Column('referral_code', sa.String(length=32), nullable=True),
        sa.Column('referred_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(), nullable=True),
        sa.Column('badge_photo_path', sa.String(length=500), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('deletion_reason', sa.Text(), nullable=True),
        sa.Column('restoration_requested_at', sa.DateTime(), nullable=True),
        sa.Column('restoration_request_status', sa.String(length=24), nullable=True),
        sa.Column('restoration_answers_json', sa.Text(), nullable=True),
        sa.Column('restoration_reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('restoration_reviewed_by', sa.String(length=160), nullable=True),
        sa.Column('restored_at', sa.DateTime(), nullable=True),
        sa.Column('probation_started_at', sa.DateTime(), nullable=True),
        sa.Column('probation_until', sa.DateTime(), nullable=True),
        sa.Column('permanent_deleted_at', sa.DateTime(), nullable=True),
        sa.Column('opportunity_interests_json', sa.Text(), nullable=True),
        sa.Column('staff_permissions_json', sa.Text(), nullable=True),
        sa.Column('registration_review_status', sa.String(length=24), nullable=False),
        sa.Column('registration_reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('registration_reviewed_by', sa.String(length=160), nullable=True),
        sa.Column('registration_rejection_reason', sa.Text(), nullable=True),
        sa.Column('ambassador_responsibility', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['referred_by_user_id'], ['users.id']),
    )

    op.create_table('web_staff_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=160), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('permissions_json', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('must_change_password', sa.Boolean(), nullable=False),
        sa.Column('failed_attempts', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('two_factor_enabled', sa.Boolean(), nullable=False),
        sa.Column('two_factor_tg_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('password_changed_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('activity_applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('activity_type_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('plan_text', sa.Text(), nullable=False),
        sa.Column('result_note', sa.Text(), nullable=False),
        sa.Column('result_image_path', sa.String(length=500), nullable=True),
        sa.Column('admin_note', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('hours_reward', sa.Float(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('completed_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['activity_type_id'], ['activity_types.id']),
        sa.ForeignKeyConstraint(['completed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('ambassador_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('photo_path', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('admin_note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_label', sa.String(length=160), nullable=False),
        sa.Column('action', sa.String(length=120), nullable=False),
        sa.Column('entity_type', sa.String(length=80), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id']),
    )

    op.create_table('ban_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('issued_by_user_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('original_ends_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('lifted_at', sa.DateTime(), nullable=True),
        sa.Column('lift_reason', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['issued_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('broadcast_campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('author_label', sa.String(length=160), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('audience_type', sa.String(length=40), nullable=False),
        sa.Column('audience_value', sa.String(length=255), nullable=True),
        sa.Column('age_min', sa.Integer(), nullable=True),
        sa.Column('age_max', sa.Integer(), nullable=True),
        sa.Column('inactive_days', sa.Integer(), nullable=True),
        sa.Column('template_code', sa.String(length=64), nullable=True),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('recipient_count', sa.Integer(), nullable=False),
        sa.Column('sent_count', sa.Integer(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id']),
    )

    op.create_table('consent_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('consent_type', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('changed_by_label', sa.String(length=160), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('content_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.String(length=32), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('tg_id', sa.BigInteger(), nullable=False),
        sa.Column('view_count', sa.Integer(), nullable=False),
        sa.Column('first_viewed_at', sa.DateTime(), nullable=False),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'entity_id', 'tg_id', name='uq_content_view_entity_tg'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('donation_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider_transaction_id', sa.String(length=160), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('amount_kop', sa.BigInteger(), nullable=False),
        sa.Column('currency_code', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('counter_name', sa.String(length=240), nullable=True),
        sa.Column('receipt_id', sa.String(length=160), nullable=True),
        sa.Column('linked_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['linked_user_id'], ['users.id']),
    )

    op.create_table('events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('location', sa.String(length=180), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('preregistration_bonus_xp', sa.Integer(), nullable=False),
        sa.Column('no_show_penalty_xp', sa.Integer(), nullable=False),
        sa.Column('volunteer_hours', sa.Float(), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('access_scope', sa.String(length=24), nullable=False),
        sa.Column('checkin_token', sa.String(length=64), nullable=False),
        sa.Column('share_token', sa.String(length=64), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('registration_template_path', sa.String(length=500), nullable=True),
        sa.Column('registration_template_name', sa.String(length=255), nullable=True),
        sa.Column('registration_template_type', sa.String(length=16), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('postponed_reason', sa.Text(), nullable=False),
        sa.Column('postponed_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )

    op.create_table('giveaway_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('report_text', sa.Text(), nullable=False),
        sa.Column('proof_photo_path', sa.String(length=500), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=160), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('giveaway_id', 'user_id', name='uq_giveaway_entry_user'),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('giveaway_prizes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
    )

    op.create_table('goals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=24), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('task_text', sa.Text(), nullable=False),
        sa.Column('metric', sa.String(length=40), nullable=False),
        sa.Column('target_value', sa.Float(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('season_id', sa.Integer(), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('reward_xp', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('ideas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('category', sa.String(length=48), nullable=False),
        sa.Column('problem', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('audience', sa.Text(), nullable=False),
        sa.Column('expected_result', sa.Text(), nullable=False),
        sa.Column('resources', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('responsible_user_id', sa.Integer(), nullable=True),
        sa.Column('admin_note', sa.Text(), nullable=False),
        sa.Column('project_team', sa.Text(), nullable=False),
        sa.Column('implementation_deadline', sa.DateTime(), nullable=True),
        sa.Column('budget_resources', sa.Text(), nullable=False),
        sa.Column('project_tasks', sa.Text(), nullable=False),
        sa.Column('progress_percent', sa.Integer(), nullable=False),
        sa.Column('implementation_result', sa.Text(), nullable=False),
        sa.Column('result_image_path', sa.String(length=500), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('implementation_started_at', sa.DateTime(), nullable=True),
        sa.Column('implemented_at', sa.DateTime(), nullable=True),
        sa.Column('approval_xp_awarded_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['responsible_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=220), nullable=True),
        sa.Column('recipient_user_id', sa.Integer(), nullable=True),
        sa.Column('recipient_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=48), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('entity_type', sa.String(length=48), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('error', sa.String(length=500), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('parse_mode', sa.String(length=24), nullable=True),
        sa.Column('button_text', sa.String(length=120), nullable=True),
        sa.Column('callback_data', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id']),
    )

    op.create_table('opportunity_interests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('opportunity_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('opportunity_id', 'user_id', name='uq_opportunity_interest_user'),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('opportunity_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('opportunity_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('reasons_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('matched_at', sa.DateTime(), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('opportunity_id', 'user_id', name='uq_opportunity_match_user'),
        sa.ForeignKeyConstraint(['opportunity_id'], ['opportunities.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('participation_streaks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('weekly_streak', sa.Integer(), nullable=False),
        sa.Column('weekly_best', sa.Integer(), nullable=False),
        sa.Column('weekly_last_key', sa.String(length=12), nullable=True),
        sa.Column('event_streak', sa.Integer(), nullable=False),
        sa.Column('event_best', sa.Integer(), nullable=False),
        sa.Column('event_started_at', sa.DateTime(), nullable=True),
        sa.Column('event_consecutive_misses', sa.Integer(), nullable=False),
        sa.Column('event_total_misses', sa.Integer(), nullable=False),
        sa.Column('event_last_processed_at', sa.DateTime(), nullable=True),
        sa.Column('recoverable_event_streak', sa.Integer(), nullable=False),
        sa.Column('recoverable_event_started_at', sa.DateTime(), nullable=True),
        sa.Column('recoverable_saved_at', sa.DateTime(), nullable=True),
        sa.Column('restores_used', sa.Integer(), nullable=False),
        sa.Column('manual_lock', sa.Boolean(), nullable=False),
        sa.Column('manual_note', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_participation_streak_user'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('quests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('quest_type', sa.String(length=24), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=True),
        sa.Column('target_value', sa.Integer(), nullable=False),
        sa.Column('progress_value', sa.Integer(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('postponed_reason', sa.Text(), nullable=False),
        sa.Column('postponed_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
    )

    op.create_table('referrals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inviter_user_id', sa.Integer(), nullable=False),
        sa.Column('invited_user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('rewarded_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoke_reason', sa.Text(), nullable=False),
        sa.Column('clawback_xp', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invited_user_id', name='uq_referral_invited_user'),
        sa.ForeignKeyConstraint(['invited_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['inviter_user_id'], ['users.id']),
    )

    op.create_table('registration_journeys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tg_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('current_step', sa.String(length=48), nullable=False),
        sa.Column('draft_ciphertext', sa.Text(), nullable=False),
        sa.Column('start_payload', sa.String(length=180), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('consent_at', sa.DateTime(), nullable=True),
        sa.Column('profile_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('first_activity_at', sa.DateTime(), nullable=True),
        sa.Column('restarted_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('request_cases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_number', sa.String(length=32), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('priority', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('assigned_user_id', sa.Integer(), nullable=True),
        sa.Column('response_deadline', sa.DateTime(), nullable=True),
        sa.Column('admin_response', sa.Text(), nullable=False),
        sa.Column('internal_note', sa.Text(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('participant_last_viewed_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('reward_claims',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reward_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('xp_spent', sa.Integer(), nullable=False),
        sa.Column('requested_at', sa.DateTime(), nullable=False),
        sa.Column('fulfilled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reward_id', 'user_id', name='uq_reward_user'),
        sa.ForeignKeyConstraint(['reward_id'], ['rewards.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('streak_freezes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('quarter_key', sa.String(length=8), nullable=False),
        sa.Column('created_by_label', sa.String(length=160), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('support_page_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('tg_id', sa.BigInteger(), nullable=True),
        sa.Column('viewed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('team_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'user_id', name='uq_team_user'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('team_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assignee_user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('deadline', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('created_by_label', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('report_text', sa.Text(), nullable=False),
        sa.Column('report_photo_path', sa.String(length=500), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=160), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=False),
        sa.Column('xp_awarded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['assignee_user_id'], ['users.id']),
    )

    op.create_table('user_badges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('badge_id', sa.Integer(), nullable=False),
        sa.Column('awarded_by', sa.Integer(), nullable=True),
        sa.Column('awarded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'badge_id', name='uq_user_badge'),
        sa.ForeignKeyConstraint(['awarded_by'], ['users.id']),
        sa.ForeignKeyConstraint(['badge_id'], ['badges.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('user_status_change_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('previous_status', sa.String(length=24), nullable=False),
        sa.Column('requested_status', sa.String(length=24), nullable=False),
        sa.Column('requested_by_label', sa.String(length=160), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('review_note', sa.Text(), nullable=False),
        sa.Column('reviewed_by_label', sa.String(length=160), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('volunteer_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('hours_reward', sa.Float(), nullable=False),
        sa.Column('deadline', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('max_participants', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('postponed_reason', sa.Text(), nullable=False),
        sa.Column('postponed_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_user_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )

    op.create_table('web_admin_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('user_agent', sa.String(length=500), nullable=False),
        sa.Column('ip_address', sa.String(length=96), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['account_id'], ['web_staff_accounts.id']),
    )

    op.create_table('broadcast_recipients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('recipient_name', sa.String(length=160), nullable=False),
        sa.Column('recipient_tg_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('error_text', sa.String(length=500), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'user_id', name='uq_broadcast_campaign_user'),
        sa.ForeignKeyConstraint(['campaign_id'], ['broadcast_campaigns.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('event_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('useful', sa.Boolean(), nullable=True),
        sa.Column('new_knowledge', sa.Boolean(), nullable=True),
        sa.Column('felt_safe', sa.Boolean(), nullable=True),
        sa.Column('would_return', sa.Boolean(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('prompted_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'user_id', name='uq_event_feedback_user'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('event_registrations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('registered_at', sa.DateTime(), nullable=False),
        sa.Column('registration_source', sa.String(length=24), nullable=False),
        sa.Column('checkin_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('attendance_signature', sa.String(length=64), nullable=True),
        sa.Column('attendance_signature_version', sa.String(length=16), nullable=True),
        sa.Column('attendance_signature_created_at', sa.DateTime(), nullable=True),
        sa.Column('attendance_confirmed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('reminder_1h_sent_at', sa.DateTime(), nullable=True),
        sa.Column('waitlisted_at', sa.DateTime(), nullable=True),
        sa.Column('waitlist_promoted_at', sa.DateTime(), nullable=True),
        sa.Column('reservation_expires_at', sa.DateTime(), nullable=True),
        sa.Column('no_show_at', sa.DateTime(), nullable=True),
        sa.Column('attendance_xp_awarded', sa.Integer(), nullable=False),
        sa.Column('preregistration_bonus_xp_awarded', sa.Integer(), nullable=False),
        sa.Column('no_show_penalty_xp_applied', sa.Integer(), nullable=False),
        sa.Column('volunteer_hours_awarded', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'user_id', name='uq_event_user'),
        sa.ForeignKeyConstraint(['attendance_confirmed_by_user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('giveaway_winners',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('prize_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('draw_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('giveaway_id', 'draw_order', name='uq_giveaway_draw_order'),
        sa.UniqueConstraint('giveaway_id', 'user_id', name='uq_giveaway_winner_user'),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prize_id'], ['giveaway_prizes.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('goal_rewards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('xp_awarded', sa.Integer(), nullable=False),
        sa.Column('awarded_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('goal_id', 'user_id', name='uq_goal_reward_user'),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('quest_participations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quest_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quest_id', 'user_id', name='uq_quest_user'),
        sa.ForeignKeyConstraint(['quest_id'], ['quests.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('request_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('sender_type', sa.String(length=24), nullable=False),
        sa.Column('sender_user_id', sa.Integer(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['case_id'], ['request_cases.id']),
        sa.ForeignKeyConstraint(['sender_user_id'], ['users.id']),
    )

    op.create_table('surveys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('xp_reward', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('audience_type', sa.String(length=24), nullable=False),
        sa.Column('audience_event_id', sa.Integer(), nullable=True),
        sa.Column('created_by_label', sa.String(length=160), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['audience_event_id'], ['events.id']),
    )

    op.create_table('team_quest_contributions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quest_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=False),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id']),
        sa.ForeignKeyConstraint(['quest_id'], ['quests.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('volunteer_task_participations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('joined_at', sa.DateTime(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('admin_note', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'user_id', name='uq_volunteer_task_user'),
        sa.ForeignKeyConstraint(['task_id'], ['volunteer_tasks.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('xp_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('season_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['event_id'], ['events.id']),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('survey_audience_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('survey_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('survey_id', 'user_id', name='uq_survey_audience_user'),
        sa.ForeignKeyConstraint(['survey_id'], ['surveys.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table('survey_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('survey_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('question_type', sa.String(length=24), nullable=False),
        sa.Column('options_text', sa.Text(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['survey_id'], ['surveys.id']),
    )

    op.create_table('survey_responses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('survey_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('answers_json', sa.Text(), nullable=False),
        sa.Column('xp_awarded', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('survey_id', 'user_id', name='uq_survey_response_user'),
        sa.ForeignKeyConstraint(['survey_id'], ['surveys.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_index('ix_activity_types_active', 'activity_types', ['active'], unique=False)
    op.create_index('ix_activity_types_category', 'activity_types', ['category'], unique=False)
    op.create_index('ix_activity_types_code', 'activity_types', ['code'], unique=True)
    op.create_index('ix_badges_badge_type', 'badges', ['badge_type'], unique=False)
    op.create_index('ux_badges_seed_key', 'badges', ['seed_key'], unique=True)
    op.create_index('ix_broadcast_templates_active', 'broadcast_templates', ['active'], unique=False)
    op.create_index('ix_donation_reports_published', 'donation_reports', ['published'], unique=False)
    op.create_index('ix_donation_reports_spent_at', 'donation_reports', ['spent_at'], unique=False)
    op.create_index('ix_giveaways_audience_type', 'giveaways', ['audience_type'], unique=False)
    op.create_index('ix_giveaways_created_at', 'giveaways', ['created_at'], unique=False)
    op.create_index('ix_giveaways_drawn_at', 'giveaways', ['drawn_at'], unique=False)
    op.create_index('ix_giveaways_ends_at', 'giveaways', ['ends_at'], unique=False)
    op.create_index('ix_giveaways_participation_mode', 'giveaways', ['participation_mode'], unique=False)
    op.create_index('ix_giveaways_starts_at', 'giveaways', ['starts_at'], unique=False)
    op.create_index('ix_giveaways_status', 'giveaways', ['status'], unique=False)
    op.create_index('ix_media_assets_category', 'media_assets', ['category'], unique=False)
    op.create_index('ix_notification_deliveries_created_at', 'notification_deliveries', ['created_at'], unique=False)
    op.create_index('ix_notification_deliveries_dedupe_key', 'notification_deliveries', ['dedupe_key'], unique=True)
    op.create_index('ix_notification_deliveries_next_retry_at', 'notification_deliveries', ['next_retry_at'], unique=False)
    op.create_index('ix_notification_deliveries_recipient_tg_id', 'notification_deliveries', ['recipient_tg_id'], unique=False)
    op.create_index('ix_notification_deliveries_source', 'notification_deliveries', ['source'], unique=False)
    op.create_index('ix_notification_deliveries_status', 'notification_deliveries', ['status'], unique=False)
    op.create_index('ix_rewards_reward_type', 'rewards', ['reward_type'], unique=False)
    op.create_index('ix_scheduled_jobs_last_success_at', 'scheduled_jobs', ['last_success_at'], unique=False)
    op.create_index('ix_scheduled_jobs_locked_until', 'scheduled_jobs', ['locked_until'], unique=False)
    op.create_index('ix_seasons_active', 'seasons', ['active'], unique=False)
    op.create_index('ix_settlement_references_active', 'settlement_references', ['active'], unique=False)
    op.create_index('ix_settlement_references_canonical_name', 'settlement_references', ['canonical_name'], unique=True)
    op.create_index('ix_users_ambassador_responsibility', 'users', ['ambassador_responsibility'], unique=False)
    op.create_index('ix_users_deleted_at', 'users', ['deleted_at'], unique=False)
    op.create_index('ix_users_last_activity_at', 'users', ['last_activity_at'], unique=False)
    op.create_index('ix_users_probation_until', 'users', ['probation_until'], unique=False)
    op.create_index('ix_users_public_token', 'users', ['public_token'], unique=True)
    op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)
    op.create_index('ix_users_registration_review_status', 'users', ['registration_review_status'], unique=False)
    op.create_index('ix_users_registration_reviewed_at', 'users', ['registration_reviewed_at'], unique=False)
    op.create_index('ix_users_restoration_request_status', 'users', ['restoration_request_status'], unique=False)
    op.create_index('ix_users_restoration_requested_at', 'users', ['restoration_requested_at'], unique=False)
    op.create_index('ix_users_tg_id', 'users', ['tg_id'], unique=True)
    op.create_index('ix_web_staff_accounts_active', 'web_staff_accounts', ['active'], unique=False)
    op.create_index('ix_web_staff_accounts_role', 'web_staff_accounts', ['role'], unique=False)
    op.create_index('ix_web_staff_accounts_username', 'web_staff_accounts', ['username'], unique=True)
    op.create_index('ix_activity_applications_activity_type_id', 'activity_applications', ['activity_type_id'], unique=False)
    op.create_index('ix_activity_applications_status', 'activity_applications', ['status'], unique=False)
    op.create_index('ix_activity_applications_user_id', 'activity_applications', ['user_id'], unique=False)
    op.create_index('ix_ambassador_reports_created_at', 'ambassador_reports', ['created_at'], unique=False)
    op.create_index('ix_ambassador_reports_period_end', 'ambassador_reports', ['period_end'], unique=False)
    op.create_index('ix_ambassador_reports_period_start', 'ambassador_reports', ['period_start'], unique=False)
    op.create_index('ix_ambassador_reports_status', 'ambassador_reports', ['status'], unique=False)
    op.create_index('ix_ambassador_reports_user_id', 'ambassador_reports', ['user_id'], unique=False)
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_ban_records_user_id', 'ban_records', ['user_id'], unique=False)
    op.create_index('ix_broadcast_campaigns_audience_type', 'broadcast_campaigns', ['audience_type'], unique=False)
    op.create_index('ix_broadcast_campaigns_created_at', 'broadcast_campaigns', ['created_at'], unique=False)
    op.create_index('ix_broadcast_campaigns_status', 'broadcast_campaigns', ['status'], unique=False)
    op.create_index('ix_consent_history_changed_at', 'consent_history', ['changed_at'], unique=False)
    op.create_index('ix_consent_history_consent_type', 'consent_history', ['consent_type'], unique=False)
    op.create_index('ix_consent_history_status', 'consent_history', ['status'], unique=False)
    op.create_index('ix_consent_history_user_id', 'consent_history', ['user_id'], unique=False)
    op.create_index('ix_content_views_entity_id', 'content_views', ['entity_id'], unique=False)
    op.create_index('ix_content_views_entity_type', 'content_views', ['entity_type'], unique=False)
    op.create_index('ix_content_views_first_viewed_at', 'content_views', ['first_viewed_at'], unique=False)
    op.create_index('ix_content_views_last_viewed_at', 'content_views', ['last_viewed_at'], unique=False)
    op.create_index('ix_content_views_tg_id', 'content_views', ['tg_id'], unique=False)
    op.create_index('ix_content_views_user_id', 'content_views', ['user_id'], unique=False)
    op.create_index('ix_donation_transactions_amount_kop', 'donation_transactions', ['amount_kop'], unique=False)
    op.create_index('ix_donation_transactions_linked_user_id', 'donation_transactions', ['linked_user_id'], unique=False)
    op.create_index('ix_donation_transactions_occurred_at', 'donation_transactions', ['occurred_at'], unique=False)
    op.create_index('ix_donation_transactions_provider_transaction_id', 'donation_transactions', ['provider_transaction_id'], unique=True)
    op.create_index('ix_events_access_scope', 'events', ['access_scope'], unique=False)
    op.create_index('ix_events_checkin_token', 'events', ['checkin_token'], unique=True)
    op.create_index('ix_events_share_token', 'events', ['share_token'], unique=True)
    op.create_index('ix_giveaway_entries_giveaway_id', 'giveaway_entries', ['giveaway_id'], unique=False)
    op.create_index('ix_giveaway_entries_status', 'giveaway_entries', ['status'], unique=False)
    op.create_index('ix_giveaway_entries_submitted_at', 'giveaway_entries', ['submitted_at'], unique=False)
    op.create_index('ix_giveaway_entries_user_id', 'giveaway_entries', ['user_id'], unique=False)
    op.create_index('ix_giveaway_prizes_giveaway_id', 'giveaway_prizes', ['giveaway_id'], unique=False)
    op.create_index('ix_goals_active', 'goals', ['active'], unique=False)
    op.create_index('ix_goals_scope', 'goals', ['scope'], unique=False)
    op.create_index('ix_goals_season_id', 'goals', ['season_id'], unique=False)
    op.create_index('ix_goals_user_id', 'goals', ['user_id'], unique=False)
    op.create_index('ix_ideas_status', 'ideas', ['status'], unique=False)
    op.create_index('ix_ideas_user_id', 'ideas', ['user_id'], unique=False)
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'], unique=False)
    op.create_index('ix_notifications_dedupe_key', 'notifications', ['dedupe_key'], unique=True)
    op.create_index('ix_notifications_entity_id', 'notifications', ['entity_id'], unique=False)
    op.create_index('ix_notifications_entity_type', 'notifications', ['entity_type'], unique=False)
    op.create_index('ix_notifications_recipient_tg_id', 'notifications', ['recipient_tg_id'], unique=False)
    op.create_index('ix_notifications_recipient_user_id', 'notifications', ['recipient_user_id'], unique=False)
    op.create_index('ix_notifications_scheduled_at', 'notifications', ['scheduled_at'], unique=False)
    op.create_index('ix_notifications_status', 'notifications', ['status'], unique=False)
    op.create_index('ix_notifications_status_type', 'notifications', ['status', 'type'], unique=False)
    op.create_index('ix_notifications_type', 'notifications', ['type'], unique=False)
    op.create_index('ix_opportunity_interests_opportunity_id', 'opportunity_interests', ['opportunity_id'], unique=False)
    op.create_index('ix_opportunity_interests_status', 'opportunity_interests', ['status'], unique=False)
    op.create_index('ix_opportunity_interests_user_id', 'opportunity_interests', ['user_id'], unique=False)
    op.create_index('ix_opportunity_matches_notified_at', 'opportunity_matches', ['notified_at'], unique=False)
    op.create_index('ix_opportunity_matches_opportunity_id', 'opportunity_matches', ['opportunity_id'], unique=False)
    op.create_index('ix_opportunity_matches_score', 'opportunity_matches', ['score'], unique=False)
    op.create_index('ix_opportunity_matches_status', 'opportunity_matches', ['status'], unique=False)
    op.create_index('ix_opportunity_matches_user_id', 'opportunity_matches', ['user_id'], unique=False)
    op.create_index('ix_opportunity_matches_user_notified', 'opportunity_matches', ['user_id', 'notified_at'], unique=False)
    op.create_index('ix_participation_streaks_user_id', 'participation_streaks', ['user_id'], unique=False)
    op.create_index('ix_quests_status', 'quests', ['status'], unique=False)
    op.create_index('ix_referrals_invited_user_id', 'referrals', ['invited_user_id'], unique=False)
    op.create_index('ix_referrals_inviter_user_id', 'referrals', ['inviter_user_id'], unique=False)
    op.create_index('ix_registration_journeys_approved_at', 'registration_journeys', ['approved_at'], unique=False)
    op.create_index('ix_registration_journeys_consent_at', 'registration_journeys', ['consent_at'], unique=False)
    op.create_index('ix_registration_journeys_current_step', 'registration_journeys', ['current_step'], unique=False)
    op.create_index('ix_registration_journeys_first_activity_at', 'registration_journeys', ['first_activity_at'], unique=False)
    op.create_index('ix_registration_journeys_profile_at', 'registration_journeys', ['profile_at'], unique=False)
    op.create_index('ix_registration_journeys_started_at', 'registration_journeys', ['started_at'], unique=False)
    op.create_index('ix_registration_journeys_submitted_at', 'registration_journeys', ['submitted_at'], unique=False)
    op.create_index('ix_registration_journeys_tg_id', 'registration_journeys', ['tg_id'], unique=True)
    op.create_index('ix_registration_journeys_updated_at', 'registration_journeys', ['updated_at'], unique=False)
    op.create_index('ix_registration_journeys_user_id', 'registration_journeys', ['user_id'], unique=False)
    op.create_index('ix_request_cases_case_number', 'request_cases', ['case_number'], unique=True)
    op.create_index('ix_request_cases_category', 'request_cases', ['category'], unique=False)
    op.create_index('ix_request_cases_participant_last_viewed_at', 'request_cases', ['participant_last_viewed_at'], unique=False)
    op.create_index('ix_request_cases_priority', 'request_cases', ['priority'], unique=False)
    op.create_index('ix_request_cases_status', 'request_cases', ['status'], unique=False)
    op.create_index('ix_request_cases_user_id', 'request_cases', ['user_id'], unique=False)
    op.create_index('ix_reward_claims_reward_id', 'reward_claims', ['reward_id'], unique=False)
    op.create_index('ix_reward_claims_user_id', 'reward_claims', ['user_id'], unique=False)
    op.create_index('ix_streak_freezes_created_at', 'streak_freezes', ['created_at'], unique=False)
    op.create_index('ix_streak_freezes_ends_at', 'streak_freezes', ['ends_at'], unique=False)
    op.create_index('ix_streak_freezes_quarter_key', 'streak_freezes', ['quarter_key'], unique=False)
    op.create_index('ix_streak_freezes_starts_at', 'streak_freezes', ['starts_at'], unique=False)
    op.create_index('ix_streak_freezes_user_id', 'streak_freezes', ['user_id'], unique=False)
    op.create_index('ix_support_page_views_tg_id', 'support_page_views', ['tg_id'], unique=False)
    op.create_index('ix_support_page_views_user_id', 'support_page_views', ['user_id'], unique=False)
    op.create_index('ix_support_page_views_viewed_at', 'support_page_views', ['viewed_at'], unique=False)
    op.create_index('ix_team_members_team_id', 'team_members', ['team_id'], unique=False)
    op.create_index('ix_team_members_user_id', 'team_members', ['user_id'], unique=False)
    op.create_index('ix_team_tasks_assignee_user_id', 'team_tasks', ['assignee_user_id'], unique=False)
    op.create_index('ix_team_tasks_created_at', 'team_tasks', ['created_at'], unique=False)
    op.create_index('ix_team_tasks_deadline', 'team_tasks', ['deadline'], unique=False)
    op.create_index('ix_team_tasks_status', 'team_tasks', ['status'], unique=False)
    op.create_index('ix_team_tasks_submitted_at', 'team_tasks', ['submitted_at'], unique=False)
    op.create_index('ix_user_badges_badge_id', 'user_badges', ['badge_id'], unique=False)
    op.create_index('ix_user_badges_user_id', 'user_badges', ['user_id'], unique=False)
    op.create_index('ix_user_status_change_requests_status', 'user_status_change_requests', ['status'], unique=False)
    op.create_index('ix_user_status_change_requests_user_id', 'user_status_change_requests', ['user_id'], unique=False)
    op.create_index('ix_web_admin_sessions_account_id', 'web_admin_sessions', ['account_id'], unique=False)
    op.create_index('ix_web_admin_sessions_expires_at', 'web_admin_sessions', ['expires_at'], unique=False)
    op.create_index('ix_web_admin_sessions_last_seen_at', 'web_admin_sessions', ['last_seen_at'], unique=False)
    op.create_index('ix_web_admin_sessions_revoked_at', 'web_admin_sessions', ['revoked_at'], unique=False)
    op.create_index('ix_web_admin_sessions_token_hash', 'web_admin_sessions', ['token_hash'], unique=True)
    op.create_index('ix_broadcast_recipients_campaign_id', 'broadcast_recipients', ['campaign_id'], unique=False)
    op.create_index('ix_broadcast_recipients_next_retry_at', 'broadcast_recipients', ['next_retry_at'], unique=False)
    op.create_index('ix_broadcast_recipients_status', 'broadcast_recipients', ['status'], unique=False)
    op.create_index('ix_broadcast_recipients_user_id', 'broadcast_recipients', ['user_id'], unique=False)
    op.create_index('ix_event_feedback_completed_at', 'event_feedback', ['completed_at'], unique=False)
    op.create_index('ix_event_feedback_event_id', 'event_feedback', ['event_id'], unique=False)
    op.create_index('ix_event_feedback_status', 'event_feedback', ['status'], unique=False)
    op.create_index('ix_event_feedback_user_id', 'event_feedback', ['user_id'], unique=False)
    op.create_index('ix_event_registrations_attendance_signature', 'event_registrations', ['attendance_signature'], unique=False)
    op.create_index('ix_event_registrations_event_id', 'event_registrations', ['event_id'], unique=False)
    op.create_index('ix_event_registrations_reservation_expires_at', 'event_registrations', ['reservation_expires_at'], unique=False)
    op.create_index('ix_event_registrations_user_id', 'event_registrations', ['user_id'], unique=False)
    op.create_index('ix_event_registrations_waitlisted_at', 'event_registrations', ['waitlisted_at'], unique=False)
    op.create_index('ux_event_registrations_attendance_signature', 'event_registrations', ['attendance_signature'], unique=True)
    op.create_index('ix_giveaway_winners_giveaway_id', 'giveaway_winners', ['giveaway_id'], unique=False)
    op.create_index('ix_giveaway_winners_prize_id', 'giveaway_winners', ['prize_id'], unique=False)
    op.create_index('ix_giveaway_winners_user_id', 'giveaway_winners', ['user_id'], unique=False)
    op.create_index('ix_goal_rewards_goal_id', 'goal_rewards', ['goal_id'], unique=False)
    op.create_index('ix_goal_rewards_user_id', 'goal_rewards', ['user_id'], unique=False)
    op.create_index('ix_quest_participations_quest_id', 'quest_participations', ['quest_id'], unique=False)
    op.create_index('ix_quest_participations_user_id', 'quest_participations', ['user_id'], unique=False)
    op.create_index('ix_request_messages_case_id', 'request_messages', ['case_id'], unique=False)
    op.create_index('ix_request_messages_created_at', 'request_messages', ['created_at'], unique=False)
    op.create_index('ix_request_messages_sender_type', 'request_messages', ['sender_type'], unique=False)
    op.create_index('ix_surveys_audience_event_id', 'surveys', ['audience_event_id'], unique=False)
    op.create_index('ix_surveys_audience_type', 'surveys', ['audience_type'], unique=False)
    op.create_index('ix_surveys_status', 'surveys', ['status'], unique=False)
    op.create_index('ix_team_quest_contributions_quest_id', 'team_quest_contributions', ['quest_id'], unique=False)
    op.create_index('ix_team_quest_contributions_user_id', 'team_quest_contributions', ['user_id'], unique=False)
    op.create_index('ix_volunteer_task_participations_status', 'volunteer_task_participations', ['status'], unique=False)
    op.create_index('ix_volunteer_task_participations_task_id', 'volunteer_task_participations', ['task_id'], unique=False)
    op.create_index('ix_volunteer_task_participations_user_id', 'volunteer_task_participations', ['user_id'], unique=False)
    op.create_index('ix_xp_transactions_season_id', 'xp_transactions', ['season_id'], unique=False)
    op.create_index('ix_xp_transactions_user_id', 'xp_transactions', ['user_id'], unique=False)
    op.create_index('ix_survey_audience_users_survey_id', 'survey_audience_users', ['survey_id'], unique=False)
    op.create_index('ix_survey_audience_users_user_id', 'survey_audience_users', ['user_id'], unique=False)
    op.create_index('ix_survey_questions_survey_id', 'survey_questions', ['survey_id'], unique=False)
    op.create_index('ix_survey_responses_survey_id', 'survey_responses', ['survey_id'], unique=False)
    op.create_index('ix_survey_responses_user_id', 'survey_responses', ['user_id'], unique=False)

def downgrade() -> None:
    op.drop_table('survey_responses')
    op.drop_table('survey_questions')
    op.drop_table('survey_audience_users')
    op.drop_table('xp_transactions')
    op.drop_table('volunteer_task_participations')
    op.drop_table('team_quest_contributions')
    op.drop_table('surveys')
    op.drop_table('request_messages')
    op.drop_table('quest_participations')
    op.drop_table('goal_rewards')
    op.drop_table('giveaway_winners')
    op.drop_table('event_registrations')
    op.drop_table('event_feedback')
    op.drop_table('broadcast_recipients')
    op.drop_table('web_admin_sessions')
    op.drop_table('volunteer_tasks')
    op.drop_table('user_status_change_requests')
    op.drop_table('user_badges')
    op.drop_table('team_tasks')
    op.drop_table('team_members')
    op.drop_table('support_page_views')
    op.drop_table('streak_freezes')
    op.drop_table('reward_claims')
    op.drop_table('request_cases')
    op.drop_table('registration_journeys')
    op.drop_table('referrals')
    op.drop_table('quests')
    op.drop_table('participation_streaks')
    op.drop_table('opportunity_matches')
    op.drop_table('opportunity_interests')
    op.drop_table('notifications')
    op.drop_table('ideas')
    op.drop_table('goals')
    op.drop_table('giveaway_prizes')
    op.drop_table('giveaway_entries')
    op.drop_table('events')
    op.drop_table('donation_transactions')
    op.drop_table('content_views')
    op.drop_table('consent_history')
    op.drop_table('broadcast_campaigns')
    op.drop_table('ban_records')
    op.drop_table('audit_logs')
    op.drop_table('ambassador_reports')
    op.drop_table('activity_applications')
    op.drop_table('web_staff_accounts')
    op.drop_table('users')
    op.drop_table('teams')
    op.drop_table('system_settings')
    op.drop_table('settlement_references')
    op.drop_table('seasons')
    op.drop_table('scheduled_jobs')
    op.drop_table('rewards')
    op.drop_table('opportunities')
    op.drop_table('notification_deliveries')
    op.drop_table('media_assets')
    op.drop_table('giveaways')
    op.drop_table('donation_reports')
    op.drop_table('donation_jar_state')
    op.drop_table('broadcast_templates')
    op.drop_table('badges')
    op.drop_table('activity_types')
