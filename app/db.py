from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings
from .models import Base

log = logging.getLogger(__name__)

# run_all.py starts the bot and web app in the same process.
# Both initialize the DB at startup, so serialize DDL for SQLite.
_db_init_lock = asyncio.Lock()


class Database:
    def __init__(self, settings: Settings):
        _backup_sqlite_before_start(settings)
        self.engine: AsyncEngine = create_async_engine(settings.database_url, echo=False, future=True, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def init(self) -> None:
        # Bot and web can call init() almost simultaneously. SQLAlchemy's
        # checkfirst is not atomic on SQLite, so two CREATE TABLE statements
        # can race. A process-wide lock prevents that for run_all.py.
        async with _db_init_lock:
            async with self.engine.begin() as conn:
                if self.engine.url.get_backend_name() == "sqlite":
                    # Better durability for a local long-running bot. WAL keeps committed
                    # data safe across normal restarts and improves concurrent reads.
                    try:
                        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                        await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                    except Exception as exc:
                        log.debug("SQLite PRAGMA setup skipped: %s", exc)
                try:
                    # create new v1.1 tables first
                    await conn.run_sync(Base.metadata.create_all)
                except OperationalError as exc:
                    # Defensive fallback for an initialization race.
                    # Re-raise unrelated database errors.
                    if "already exists" not in str(exc).lower():
                        raise
                    log.info("Concurrent DB initialization detected; continuing: %s", exc)

                # lightweight compatibility migration for a v1.0 database
                await conn.run_sync(_migrate_v10_to_v11)

                # create indexes that can be added after columns exist
                for sql in [
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_public_token ON users(public_token)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_referral_code ON users(referral_code)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_events_share_token ON events(share_token)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_event_registrations_attendance_signature ON event_registrations(attendance_signature)",
                    "CREATE INDEX IF NOT EXISTS ix_xp_transactions_season_id ON xp_transactions(season_id)",
                    "CREATE INDEX IF NOT EXISTS ix_users_last_activity_at ON users(last_activity_at)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_request_cases_case_number ON request_cases(case_number)",
                    "CREATE INDEX IF NOT EXISTS ix_request_cases_participant_last_viewed_at ON request_cases(participant_last_viewed_at)",
                    "CREATE INDEX IF NOT EXISTS ix_broadcast_recipients_next_retry_at ON broadcast_recipients(next_retry_at)",
                    "CREATE INDEX IF NOT EXISTS ix_scheduled_jobs_locked_until ON scheduled_jobs(locked_until)",
                    "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_next_retry_at ON notification_deliveries(next_retry_at)",
                    "CREATE INDEX IF NOT EXISTS ix_notifications_scheduled_at ON notifications(scheduled_at)",
                    "CREATE INDEX IF NOT EXISTS ix_notifications_status_type ON notifications(status, type)",
                    "CREATE INDEX IF NOT EXISTS ix_event_feedback_event_id ON event_feedback(event_id)",
                    "CREATE INDEX IF NOT EXISTS ix_event_feedback_completed_at ON event_feedback(completed_at)",
                    "CREATE INDEX IF NOT EXISTS ix_event_registrations_waitlisted_at ON event_registrations(waitlisted_at)",
                    "CREATE INDEX IF NOT EXISTS ix_event_registrations_reservation_expires_at ON event_registrations(reservation_expires_at)",
                    "CREATE INDEX IF NOT EXISTS ix_opportunity_matches_user_notified ON opportunity_matches(user_id, notified_at)",
                    "CREATE INDEX IF NOT EXISTS ix_opportunity_matches_score ON opportunity_matches(score)",
                ]:
                    try:
                        await conn.exec_driver_sql(sql)
                    except Exception as exc:
                        log.debug("Index migration skipped: %s", exc)

                # v1.9.0: consolidate the complete legacy durable outbox into the
                # canonical notifications table. A stable synthetic key is used for
                # historical rows that never had dedupe_key, so the migration is safe
                # to repeat on every startup without losing queued/retry messages.
                try:
                    await conn.exec_driver_sql("""
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
                    """)
                except Exception as exc:
                    log.debug("Legacy notification migration skipped: %s", exc)

    async def close(self) -> None:
        await self.engine.dispose()


def _backup_sqlite_before_start(settings: Settings) -> None:
    """Create a lightweight daily safety copy before schema migrations.

    Operational data live outside the version folder, so this backup is also
    preserved when a new application archive is unpacked.
    """
    if not settings.database_url.startswith("sqlite+aiosqlite:///"):
        return
    raw = settings.database_url.removeprefix("sqlite+aiosqlite:///")
    db_path = Path(raw).expanduser()
    if not db_path.exists() or db_path.stat().st_size == 0:
        return
    backup_dir = Path(settings.data_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    target = backup_dir / f"amp_bot_{stamp}.db"
    if target.exists():
        return
    try:
        shutil.copy2(db_path, target)
    except OSError as exc:
        log.warning("Не вдалося створити резервну копію SQLite: %s", exc)


def _migrate_v10_to_v11(sync_conn) -> None:
    """Small idempotent migration so a test v1.0 DB can be reused.

    For long-term production use, keep backups and migrate via a proper migration tool.
    """
    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())

    def columns(table: str) -> set[str]:
        if table not in tables:
            return set()
        return {c["name"] for c in insp.get_columns(table)}

    migrations: dict[str, list[tuple[str, str]]] = {
        "users": [
            ("public_token", "VARCHAR(64)"),
            ("wallet_xp", "INTEGER DEFAULT 0"),
            ("referral_code", "VARCHAR(32)"),
            ("referred_by_user_id", "INTEGER"),
            ("first_name", "VARCHAR(80)"),
            ("last_name", "VARCHAR(80)"),
            ("email", "VARCHAR(160)"),
            ("gender", "VARCHAR(24)"),
            ("vulnerability_categories", "TEXT"),
            ("media_consent", "BOOLEAN"),
            ("media_consent_status", "VARCHAR(24) DEFAULT 'pending'"),
            ("media_consent_version", "VARCHAR(32)"),
            ("media_consent_recorded_at", "TIMESTAMP"),
            ("privacy_notice_version", "VARCHAR(32)"),
            ("privacy_acknowledged_at", "TIMESTAMP"),
            ("birthday_reward_year", "INTEGER"),
            ("blocked_until", "TIMESTAMP"),
            ("block_reason", "TEXT"),
            ("last_activity_at", "TIMESTAMP"),
            ("badge_photo_path", "VARCHAR(500)"),
            ("parental_consent_status", "VARCHAR(24) DEFAULT 'not_required'"),
            ("parental_consent_received_at", "TIMESTAMP"),
            ("parental_consent_file_path", "VARCHAR(500)"),
            ("deleted_at", "TIMESTAMP"),
            ("deletion_reason", "TEXT"),
            ("restoration_requested_at", "TIMESTAMP"),
            ("restoration_request_status", "VARCHAR(24)"),
            ("restoration_answers_json", "TEXT"),
            ("restoration_reviewed_at", "TIMESTAMP"),
            ("restoration_reviewed_by", "VARCHAR(160)"),
            ("restored_at", "TIMESTAMP"),
            ("probation_started_at", "TIMESTAMP"),
            ("probation_until", "TIMESTAMP"),
            ("permanent_deleted_at", "TIMESTAMP"),
            ("opportunity_interests_json", "TEXT"),
            ("staff_permissions_json", "TEXT"),
            ("registration_review_status", "VARCHAR(24) DEFAULT 'approved'"),
            ("registration_reviewed_at", "TIMESTAMP"),
            ("registration_reviewed_by", "VARCHAR(160)"),
            ("registration_rejection_reason", "TEXT"),
        ],
        "web_staff_accounts": [
            ("permissions_json", "TEXT"),
        ],
        "seasons": [
            ("finalized_at", "TIMESTAMP"),
            ("history_json", "TEXT"),
        ],
        "xp_transactions": [
            ("season_id", "INTEGER"),
        ],
        "event_registrations": [
            ("reminder_1h_sent_at", "TIMESTAMP"),
            ("attendance_signature", "VARCHAR(64)"),
            ("attendance_signature_version", "VARCHAR(16)"),
            ("attendance_signature_created_at", "TIMESTAMP"),
            ("attendance_confirmed_by_user_id", "INTEGER"),
            ("waitlisted_at", "TIMESTAMP"),
            ("waitlist_promoted_at", "TIMESTAMP"),
            ("reservation_expires_at", "TIMESTAMP"),
            ("no_show_at", "TIMESTAMP"),
        ],
        "events": [
            ("image_path", "VARCHAR(500)"),
            ("share_token", "VARCHAR(64)"),
            ("registration_template_path", "VARCHAR(500)"),
            ("registration_template_name", "VARCHAR(255)"),
            ("registration_template_type", "VARCHAR(16)"),
            ("cancellation_reason", "TEXT DEFAULT ''"),
            ("cancelled_at", "TIMESTAMP"),
            ("postponed_reason", "TEXT DEFAULT ''"),
            ("postponed_at", "TIMESTAMP"),
        ],
        "quests": [
            ("quest_type", "VARCHAR(24) DEFAULT 'individual'"),
            ("team_id", "INTEGER"),
            ("target_value", "INTEGER DEFAULT 1"),
            ("progress_value", "INTEGER DEFAULT 0"),
            ("completed", "BOOLEAN DEFAULT FALSE"),
            ("status", "VARCHAR(24) DEFAULT 'open'"),
            ("image_path", "VARCHAR(500)"),
            ("cancellation_reason", "TEXT DEFAULT ''"),
            ("cancelled_at", "TIMESTAMP"),
            ("postponed_reason", "TEXT DEFAULT ''"),
            ("postponed_at", "TIMESTAMP"),
        ],
        "badges": [
            ("criteria_type", "VARCHAR(64)"),
            ("criteria_value", "INTEGER"),
            ("automatic", "BOOLEAN DEFAULT FALSE"),
            ("image_path", "VARCHAR(500)"),
            ("badge_type", "VARCHAR(24) DEFAULT 'general'"),
        ],
        "request_cases": [
            ("image_path", "VARCHAR(500)"),
            ("case_number", "VARCHAR(32)"),
            ("response_deadline", "TIMESTAMP"),
            ("participant_last_viewed_at", "TIMESTAMP"),
        ],
        "volunteer_tasks": [
            ("max_participants", "INTEGER DEFAULT 1"),
            ("image_path", "VARCHAR(500)"),
            ("cancellation_reason", "TEXT DEFAULT ''"),
            ("cancelled_at", "TIMESTAMP"),
            ("postponed_reason", "TEXT DEFAULT ''"),
            ("postponed_at", "TIMESTAMP"),
        ],
        "opportunities": [
            ("image_path", "VARCHAR(500)"),
            ("direction", "VARCHAR(100) DEFAULT 'Інше'"),
            ("format", "VARCHAR(80) DEFAULT 'Онлайн/офлайн'"),
            ("age_min", "INTEGER"),
            ("age_max", "INTEGER"),
            ("updated_at", "TIMESTAMP"),
            ("target_settlements", "TEXT"),
        ],
        "ideas": [
            ("category", "VARCHAR(48) DEFAULT 'other'"),
            ("problem", "TEXT DEFAULT ''"),
            ("audience", "TEXT DEFAULT ''"),
            ("expected_result", "TEXT DEFAULT ''"),
            ("resources", "TEXT DEFAULT ''"),
            ("responsible_user_id", "INTEGER"),
            ("admin_note", "TEXT DEFAULT ''"),
            ("updated_at", "TIMESTAMP"),
            ("project_team", "TEXT DEFAULT ''"),
            ("implementation_deadline", "TIMESTAMP"),
            ("budget_resources", "TEXT DEFAULT ''"),
            ("project_tasks", "TEXT DEFAULT ''"),
            ("progress_percent", "INTEGER DEFAULT 0"),
            ("implementation_result", "TEXT DEFAULT ''"),
            ("result_image_path", "VARCHAR(500)"),
            ("approved_at", "TIMESTAMP"),
            ("implementation_started_at", "TIMESTAMP"),
            ("implemented_at", "TIMESTAMP"),
            ("approval_xp_awarded_at", "TIMESTAMP"),
        ],
        "activity_applications": [
            ("result_image_path", "VARCHAR(500)"),
        ],
        "goals": [
            ("task_text", "TEXT DEFAULT ''"),
            ("reward_xp", "INTEGER DEFAULT 0"),
            ("image_path", "VARCHAR(500)"),
        ],
        "rewards": [
            ("image_path", "VARCHAR(500)"),
            ("reward_type", "VARCHAR(32) DEFAULT 'item'"),
        ],
        "referrals": [
            ("revoked_at", "TIMESTAMP"),
            ("revoke_reason", "TEXT DEFAULT ''"),
            ("clawback_xp", "INTEGER DEFAULT 0"),
        ],
        "reward_claims": [
            ("xp_spent", "INTEGER DEFAULT 0"),
        ],
        "survey_questions": [
            ("image_path", "VARCHAR(500)"),
        ],
        "broadcast_recipients": [
            ("attempt_count", "INTEGER DEFAULT 0"),
            ("last_attempt_at", "TIMESTAMP"),
            ("next_retry_at", "TIMESTAMP"),
        ],
        "notification_deliveries": [
            ("button_text", "VARCHAR(120)"),
            ("callback_data", "VARCHAR(120)"),
        ],
    }

    # v1.2 spendable wallet: preserve lifetime XP while rewards consume wallet XP.
    # For existing databases seed an empty wallet from all historical earned XP once.
    if "users" in tables and "xp_transactions" in tables:
        user_cols_before = columns("users")
        wallet_was_missing = "wallet_xp" not in user_cols_before
    else:
        wallet_was_missing = False

    for table, defs in migrations.items():
        existing = columns(table)
        for col, ddl in defs:
            if col in existing:
                continue
            try:
                sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                log.info("DB migration: added %s.%s", table, col)
            except Exception as exc:
                log.warning("Could not add %s.%s: %s", table, col, exc)


    # v1.10.4: split the registration intake queue from the participant base.
    # Existing non-pending profiles are already reviewed; legacy pending profiles
    # stay in the incoming registration queue.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "users" in tables_now and "registration_review_status" in columns("users"):
            sync_conn.exec_driver_sql("UPDATE users SET registration_review_status='pending' WHERE status='pending'")
            sync_conn.exec_driver_sql("UPDATE users SET registration_review_status='approved' WHERE status<>'pending' AND (registration_review_status IS NULL OR registration_review_status='' OR registration_review_status='pending')")
    except Exception as exc:
        log.warning("Could not initialize v1.10.4 registration review fields: %s", exc)

    # v1.6.8: initialize current consent state for legacy profiles.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "users" in tables_now:
            user_cols = columns("users")
            if "media_consent_status" in user_cols:
                sync_conn.exec_driver_sql("UPDATE users SET media_consent_status=CASE WHEN media_consent=TRUE THEN 'granted' WHEN media_consent=FALSE THEN 'declined' ELSE 'pending' END WHERE media_consent_status IS NULL OR media_consent_status='' OR media_consent_status='pending'")
            if "parental_consent_status" in user_cols:
                sync_conn.exec_driver_sql("UPDATE users SET parental_consent_status=CASE WHEN parental_consent_required=FALSE THEN 'not_required' WHEN parental_consent_confirmed=TRUE THEN 'received' ELSE 'pending' END WHERE parental_consent_status IS NULL OR parental_consent_status='' OR parental_consent_status='not_required'")
    except Exception as exc:
        log.warning("Could not initialize v1.6.8 consent fields: %s", exc)

    # v1.6.6: backfill human-readable case numbers and initialize case threads.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "request_cases" in tables_now and "case_number" in columns("request_cases"):
            if sync_conn.dialect.name == "postgresql":
                sync_conn.exec_driver_sql("""
                    UPDATE request_cases
                    SET case_number = 'AMP-' || EXTRACT(YEAR FROM COALESCE(created_at, CURRENT_TIMESTAMP))::int || '-' || LPAD(id::text, 4, '0')
                    WHERE case_number IS NULL OR case_number=''
                """)
            else:
                sync_conn.exec_driver_sql("""
                    UPDATE request_cases
                    SET case_number = 'AMP-' || strftime('%Y', COALESCE(created_at, CURRENT_TIMESTAMP)) || '-' || printf('%04d', id)
                    WHERE case_number IS NULL OR case_number=''
                """)
        if "request_messages" in tables_now and "request_cases" in tables_now:
            sync_conn.exec_driver_sql("""
                INSERT INTO request_messages (case_id, sender_type, sender_user_id, body, image_path, created_at)
                SELECT r.id, 'participant', r.user_id, COALESCE(r.description,''), r.image_path, COALESCE(r.created_at, CURRENT_TIMESTAMP)
                FROM request_cases r
                WHERE NOT EXISTS (SELECT 1 FROM request_messages m WHERE m.case_id=r.id)
            """)
    except Exception as exc:
        log.warning("Could not backfill v1.6.6 request cases: %s", exc)

    # v1.6.5: normalize new lifecycle fields for legacy data.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "quests" in tables_now and "status" in columns("quests"):
            sync_conn.exec_driver_sql("UPDATE quests SET status='cancelled' WHERE cancelled_at IS NOT NULL")
            sync_conn.exec_driver_sql("UPDATE quests SET status='completed' WHERE completed=TRUE AND cancelled_at IS NULL")
            sync_conn.exec_driver_sql("UPDATE quests SET status='open' WHERE status IS NULL OR status='' ")
        if "opportunities" in tables_now and "updated_at" in columns("opportunities"):
            sync_conn.exec_driver_sql("UPDATE opportunities SET updated_at=created_at WHERE updated_at IS NULL")
    except Exception as exc:
        log.warning("Could not normalize v1.6.5 lifecycle fields: %s", exc)

    # v1.6.2: initialize activity timestamps for legacy profiles so the
    # communication-center "inactive" filter behaves predictably immediately
    # after deployment. New Telegram interactions keep this field fresh.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "users" in tables_now and "last_activity_at" in columns("users"):
            sync_conn.exec_driver_sql(
                "UPDATE users SET last_activity_at = created_at WHERE last_activity_at IS NULL"
            )
    except Exception as exc:
        log.warning("Could not initialize users.last_activity_at: %s", exc)

    # v1.5: preserve legacy one-person volunteer-task assignments in the new
    # many-participant table. The INSERT is idempotent because of UNIQUE(task_id,user_id).
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "volunteer_tasks" in tables_now and "volunteer_task_participations" in tables_now:
            insert_sql = """
                INSERT {ignore_clause} INTO volunteer_task_participations
                    (task_id, user_id, status, joined_at, submitted_at, approved_at, admin_note)
                SELECT id, assigned_user_id,
                       CASE status
                         WHEN 'submitted' THEN 'submitted'
                         WHEN 'done' THEN 'approved'
                         ELSE 'joined'
                       END,
                       COALESCE(created_at, CURRENT_TIMESTAMP),
                       CASE WHEN status IN ('submitted','done') THEN CURRENT_TIMESTAMP ELSE NULL END,
                       CASE WHEN status='done' THEN CURRENT_TIMESTAMP ELSE NULL END,
                       ''
                FROM volunteer_tasks
                WHERE assigned_user_id IS NOT NULL
                {conflict_clause}
            """
            if sync_conn.dialect.name == "postgresql":
                sql = insert_sql.format(ignore_clause="", conflict_clause="ON CONFLICT (task_id, user_id) DO NOTHING")
            else:
                sql = insert_sql.format(ignore_clause="OR IGNORE", conflict_clause="")
            sync_conn.exec_driver_sql(sql)
            sync_conn.exec_driver_sql("UPDATE volunteer_tasks SET status='open' WHERE status IN ('assigned','submitted')")
            sync_conn.exec_driver_sql("UPDATE volunteer_tasks SET status='closed' WHERE status='done'")
    except Exception as exc:
        log.warning("Legacy volunteer task migration skipped: %s", exc)

    # v1.5.1: preserve legacy temporary bans in the dedicated moderation history.
    try:
        tables_now = set(inspect(sync_conn).get_table_names())
        if "users" in tables_now and "ban_records" in tables_now:
            if sync_conn.dialect.name == "postgresql":
                fallback_end = "CURRENT_TIMESTAMP + INTERVAL '7 days'"
            else:
                fallback_end = "datetime('now', '+7 day')"
            sync_conn.exec_driver_sql(
                f"""
                INSERT INTO ban_records
                    (user_id, issued_by_user_id, source, reason, started_at, original_ends_at, ends_at, lifted_at, lift_reason, updated_at)
                SELECT u.id, NULL, 'legacy', COALESCE(u.block_reason, 'Тимчасове блокування'),
                       CURRENT_TIMESTAMP,
                       COALESCE(u.blocked_until, {fallback_end}),
                       COALESCE(u.blocked_until, {fallback_end}),
                       NULL, NULL, CURRENT_TIMESTAMP
                FROM users u
                WHERE u.status='blocked'
                  AND NOT EXISTS (
                      SELECT 1 FROM ban_records b
                      WHERE b.user_id=u.id AND b.lifted_at IS NULL
                  )
                """
            )
    except Exception as exc:
        log.warning("Legacy ban history migration skipped: %s", exc)

    if wallet_was_missing:
        try:
            sync_conn.exec_driver_sql(
                "UPDATE users SET wallet_xp = COALESCE((SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE amount END) FROM xp_transactions WHERE xp_transactions.user_id = users.id), 0)"
            )
            sync_conn.exec_driver_sql("UPDATE users SET wallet_xp = 0 WHERE wallet_xp < 0")
            log.info("DB migration: seeded users.wallet_xp from XP history")
        except Exception as exc:
            log.warning("Could not seed wallet XP: %s", exc)
