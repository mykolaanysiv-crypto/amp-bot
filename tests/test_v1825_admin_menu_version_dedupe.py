from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v1825_version_and_css_cache():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "1.12.0"
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == "1.12.0"
    base = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "/static/admin.css?v=1.12.0" in base


def test_version_notice_uses_unique_per_user_outbox_dedupe():
    source = (ROOT / "app/web/app.py").read_text(encoding="utf-8")
    announce = source[source.index("async def _announce_version_update_locked"):source.index("async def _recover_pending_broadcasts")]
    assert 'dedupe_key=f"system_version_update:{APP_VERSION}:user:{user.id}"' in announce
    assert 'source="system_version_update"' in announce
    assert "_queue_system_broadcast(" not in announce
    assert "_retire_legacy_version_broadcasts()" in source
    assert source.index("await _retire_legacy_version_broadcasts()") < source.index("await _recover_pending_broadcasts()")


def test_outbox_dedupe_is_race_safe_and_job_lock_not_reentrant():
    source = (ROOT / "app/reliability.py").read_text(encoding="utf-8")
    acquire = source[source.index("async def acquire_job_lock"):source.index("async def finish_job_lock")]
    assert "ScheduledJob.locked_by == owner" not in acquire
    queue = source[source.index("async def queue_notification"):source.index("def _retry_delay")]
    assert "session.begin_nested()" in queue
    assert "except IntegrityError" in queue
    assert "Notification.dedupe_key == dedupe_key" in queue


def test_admin_panel_is_two_level_and_role_aware():
    kb = (ROOT / "app/keyboards.py").read_text(encoding="utf-8")
    main = kb[kb.index("def admin_menu(role: str,"):kb.index("def admin_section_menu")]
    for callback in (
        "admin:section:events",
        "admin:section:activities",
        "admin:section:gamification",
        "admin:section:people",
        "admin:section:data",
    ):
        assert callback in main
    # Detailed actions moved out of the top level.
    assert "admin:create_event" not in main
    assert "admin:create_quest" not in main
    assert "admin:add_xp" not in main
    assert "admin:broadcast" not in main

    sections = kb[kb.index("def admin_section_menu"):kb.index("def pending_user_keyboard")]
    for callback in (
        "admin:create_event", "admin:attendance", "admin:event_scanner", "admin:event_qr",
        "admin:create_quest", "admin:quest_approvals", "admin:activity_apps", "admin:create_task",
        "admin:task_approvals", "admin:create_opportunity", "admin:add_xp", "admin:award_badge",
        "admin:pending", "admin:analytics", "admin:export", "admin:menu",
    ):
        assert callback in sections
    assert '"moderation.manage" in perms' in sections
    assert '"broadcast.send" in perms' in sections
    assert '"admin:moderation"' in sections
    assert '"admin:broadcast"' in sections


def test_admin_handlers_support_root_and_sections():
    source = "\n".join((ROOT / "app/handlers" / name).read_text(encoding="utf-8") for name in ['admin.py', 'admin_common.py', 'admin_core.py', 'admin_events.py', 'admin_quests_rewards.py', 'admin_activities_tasks.py', 'admin_opportunities.py', 'admin_moderation.py'])
    assert '@router.callback_query(F.data == "admin:menu")' in source
    assert '@router.callback_query(F.data.startswith("admin:section:"))' in source
    assert "admin_section_menu(admin.role, section, _staff_permissions(admin))" in source
