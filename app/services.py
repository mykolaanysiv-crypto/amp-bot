"""Backward-compatible service facade.

Canonical service implementations live under ``app.domain_services``.  v1.13.0
keeps this facade for 1–2 releases but no longer uses wildcard imports.
"""
from .domain_services import (
    age_on, get_user_by_tg, get_user, ensure_user_tokens,
    current_season, ensure_default_season, xp_total, season_xp, add_xp,
    process_birthdays, seed_activity_types, complete_activity_application,
    seed_badges, evaluate_automatic_badges, seed_streak_restore_reward,
    seed_default_space_rewards, process_expired_bans, create_event,
    register_for_event, join_event_waitlist, accept_event_reservation,
    process_event_operations, event_checkin_window, checkin_for_event,
    confirm_single_event_attendance, admin_scan_event_participant,
    confirm_event_attendance, log_audit, seed_default_team,
    add_active_users_to_default_team, complete_team_quest,
    create_referral_for_user, referral_quarter_bounds, referral_quarter_summary,
    reward_referral_if_ready, revoke_referral_reward_if_inactive,
    ensure_superadmins, ensure_web_staff_accounts, ensure_event_share_tokens,
    bootstrap_defaults, build_profile_qr_png, export_event_participants_pdf,
    export_event_participants_excel, export_basic_excel, export_excel,
)

__all__ = [name for name in (
    "age_on", "get_user_by_tg", "get_user", "ensure_user_tokens",
    "current_season", "ensure_default_season", "xp_total", "season_xp", "add_xp",
    "process_birthdays", "seed_activity_types", "complete_activity_application",
    "seed_badges", "evaluate_automatic_badges", "seed_streak_restore_reward",
    "seed_default_space_rewards", "process_expired_bans", "create_event",
    "register_for_event", "join_event_waitlist", "accept_event_reservation",
    "process_event_operations", "event_checkin_window", "checkin_for_event",
    "confirm_single_event_attendance", "admin_scan_event_participant",
    "confirm_event_attendance", "log_audit", "seed_default_team",
    "add_active_users_to_default_team", "complete_team_quest",
    "create_referral_for_user", "referral_quarter_bounds", "referral_quarter_summary",
    "reward_referral_if_ready", "revoke_referral_reward_if_inactive",
    "ensure_superadmins", "ensure_web_staff_accounts", "ensure_event_share_tokens",
    "bootstrap_defaults", "build_profile_qr_png", "export_event_participants_pdf",
    "export_event_participants_excel", "export_basic_excel", "export_excel",
)]
