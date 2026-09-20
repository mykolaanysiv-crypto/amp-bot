from pathlib import Path

from app.model_domains import Base, UserRole
from app.permissions import ALL_PERMISSIONS, effective_permissions, has_permission, required_web_permission, required_web_any_permissions
from app.profile_data import split_display_name
from tests.source_layout import event_routes_source, web_app_source

ROOT = Path(__file__).resolve().parents[1]


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_and_schema_stay_additive():
    version = text("VERSION.txt").strip()
    assert version
    assert text("VERSION_CHECK.txt").strip() == version
    assert len(Base.metadata.tables) >= 53
    assert "staff_permissions_json" in Base.metadata.tables["users"].c
    assert "permissions_json" in Base.metadata.tables["web_staff_accounts"].c

    # v1.17.1 Full Alembic Adoption: historical schema ownership lives in
    # Alembic, never in Database.init()/a runtime migrations mapping.
    baseline = text("migrations/versions/20260915_0001_v1111_baseline.py")
    assert "sa.Column('staff_permissions_json', sa.Text(), nullable=True)" in baseline
    assert "sa.Column('permissions_json', sa.Text(), nullable=True)" in baseline
    db = text("app/db.py")
    assert "_migrate_v10_to_v11" not in db
    assert "Base.metadata.create_all" not in db


def test_granular_permissions_defaults_and_explicit_override():
    assert "participants.view" in ALL_PERMISSIONS
    assert "events.create" in ALL_PERMISSIONS
    assert "events.edit" in ALL_PERMISSIONS
    assert "events.delete" in ALL_PERMISSIONS
    assert "xp.award" in ALL_PERMISSIONS
    assert "reports.basic_export" in ALL_PERMISSIONS
    assert "reports.sensitive_export" in ALL_PERMISSIONS
    assert "broadcast.send" in ALL_PERMISSIONS
    assert "moderation.manage" in ALL_PERMISSIONS
    assert effective_permissions(UserRole.SUPERADMIN.value, None) == ALL_PERMISSIONS
    assert has_permission(UserRole.ADMIN.value, None, "participants.approve")
    assert not has_permission(UserRole.ADMIN.value, None, "reports.sensitive_export")
    assert effective_permissions(UserRole.ADMIN.value, "[]") == frozenset()
    assert effective_permissions(UserRole.ADMIN.value, "not-json") == frozenset()


def test_web_permission_safety_net_maps_sensitive_actions():
    assert required_web_permission("/admin/users", "GET") == "participants.view"
    assert required_web_permission("/admin/users/7/xp", "POST") == "xp.award"
    assert required_web_permission("/admin/users/7/activate", "POST") == "participants.approve"
    assert required_web_permission("/admin/events/create", "POST") == "events.create"
    assert required_web_permission("/admin/events/4/delete", "POST") == "events.delete"
    assert required_web_permission("/admin/export/sensitive", "GET") == "reports.sensitive_export"
    assert required_web_permission("/admin/broadcasts", "GET") == "broadcast.send"
    assert required_web_permission("/admin/moderation", "GET") == "moderation.manage"


def test_security_page_can_manage_web_and_telegram_permissions():
    app = web_app_source()
    tpl = text("app/web/templates/security_accounts.html")
    middleware = text("app/web/security_middleware.py")
    assert '/admin/security/accounts/{account_id}/permissions' in app
    assert '/admin/security/telegram/{user_id}/permissions' in app
    assert 'name="permissions"' in tpl
    assert "permission_groups" in tpl
    assert "telegram_staff" in tpl
    assert "admin_permissions" in middleware
    assert "required_web_permission" in middleware


def test_telegram_admin_menu_is_permission_driven():
    kb = text("app/keyboards.py")
    admin = (text("app/handlers/admin.py") + text("app/handlers/admin_common.py") + text("app/handlers/admin_core.py") + text("app/handlers/admin_events.py") + text("app/handlers/admin_quests_rewards.py") + text("app/handlers/admin_activities_tasks.py") + text("app/handlers/admin_opportunities.py") + text("app/handlers/admin_moderation.py"))
    for perm in [
        "events.create", "events.edit", "participants.approve", "moderation.manage",
        "xp.award", "reports.basic_export", "broadcast.send", "analytics.view",
    ]:
        assert perm in kb or perm in admin
    assert "AdminCallbackPermissionMiddleware" in admin
    assert "_callback_permission" in admin


def test_main_menu_surfaces_invite_and_requests_and_uses_first_name():
    kb = text("app/keyboards.py")
    participant = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    for row in [
        '[KeyboardButton(text="🏠 Головна"), KeyboardButton(text="👤 Мій профіль")]',
        '[KeyboardButton(text="🚀 Долучитися"), KeyboardButton(text="🌍 Можливості")]',
        '[KeyboardButton(text="🎫 QR-бейдж"), KeyboardButton(text="🤝 Запросити друга")]',
        '[KeyboardButton(text="💙 Підтримати"), KeyboardButton(text="🆘 Звернення")]',
        '[KeyboardButton(text="☰ Ще")]',
    ]:
        assert row in kb
    # They should no longer be hidden inside the profile/more second-level hubs.
    profile_block = kb[kb.index("def profile_hub_keyboard"):kb.index("def more_hub_keyboard")]
    more_block = kb[kb.index("def more_hub_keyboard"):kb.index("def registration_phone_keyboard")]
    assert "Запрошення" not in profile_block
    assert "Звернення" not in more_block
    assert "participant_first_name(user)" in participant
    assert "Твій прогрес" in participant
    assert "Швидкі дії" not in participant
    assert "Наступний крок" in participant
    assert "progress_bar" in participant
    assert "Для винагород" in participant


def test_role_change_and_admin_callbacks_use_granular_permissions():
    admin = (text("app/handlers/admin.py") + text("app/handlers/admin_common.py") + text("app/handlers/admin_core.py") + text("app/handlers/admin_events.py") + text("app/handlers/admin_quests_rewards.py") + text("app/handlers/admin_activities_tasks.py") + text("app/handlers/admin_opportunities.py") + text("app/handlers/admin_moderation.py"))
    assert 'has_permission(admin.role, admin.staff_permissions_json, "security.manage")' in admin
    assert 'AdminCallbackPermissionMiddleware' in admin
    assert '"participants.approve"' in admin
    assert '"moderation.manage"' in admin
    assert '"broadcast.send"' in admin


def test_home_progress_uses_real_level_thresholds():
    participant = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert "from ..gamification import LEVELS" in participant
    assert "current_threshold = max((threshold for threshold, _ in LEVELS if threshold <= xp)" in participant


def test_participants_edit_has_a_non_sensitive_web_workflow():
    users = text("app/web/routes/users.py")
    detail = text("app/web/templates/user_detail.html")
    assert '/admin/users/{user_id}/basic-profile' in users
    assert 'guard_permission(request, "participants.edit")' in users
    assert 'web_user_basic_profile_update' in users
    assert 'has_permission("participants.edit")' in detail
    assert 'Базові дані учасника' in detail


def test_read_access_is_not_only_hidden_in_the_sidebar():
    assert set(required_web_any_permissions("/admin/events", "GET")) == {"events.create", "events.edit", "events.delete"}
    assert required_web_any_permissions("/admin/quests/4", "GET") == ("quests.manage",)
    assert required_web_any_permissions("/admin/requests", "GET") == ("cases.manage",)
    middleware = text("app/web/security_middleware.py")
    assert "required_web_any_permissions" in middleware
    assert "current_permissions.intersection(any_permissions)" in middleware


def test_global_search_and_attention_are_permission_filtered():
    search = text("app/web/routes/adminux.py")
    dashboard = text("app/web/routes/dashboard.py")
    assert 'can_users = "participants.view" in perms' in search
    assert 'can_cases = "cases.manage" in perms' in search
    assert 'can_ideas = "ideas.manage" in perms' in search
    assert 'has_web_permission(request, "participants.approve")' in dashboard
    assert 'has_web_permission(request, "notifications.manage")' in dashboard


def test_legacy_names_address_participants_by_first_name():
    first, last = split_display_name("Прохоренко Микола", None, None)
    assert first == "Микола"
    assert last == "Прохоренко"
    first, last = split_display_name("Кумеда Данило", None, None)
    assert first == "Данило"
    participant = (text("app/handlers/participant.py") + text("app/handlers/participant_common.py") + text("app/handlers/participant_home.py") + text("app/handlers/participant_requests.py") + text("app/handlers/participant_opportunities.py") + text("app/handlers/participant_activities.py") + text("app/handlers/participant_tasks.py"))
    assert "participant_first_name(user)" in participant


def test_role_change_resets_custom_telegram_permissions():
    users = text("app/web/routes/users.py")
    assert "user.staff_permissions_json = None" in users
    assert "permissions=role_defaults" in users


def test_sensitive_event_exports_follow_the_granular_permission():
    events = event_routes_source()
    tpl = text("app/web/templates/event_detail.html")
    assert 'guard_permission(request, "reports.sensitive_export")' in events
    assert 'include_sensitive = has_web_permission(request, "reports.sensitive_export")' in events
    assert 'has_permission("reports.sensitive_export")' in tpl


def test_telegram_role_change_clears_stale_custom_acl():
    admin = (text("app/handlers/admin.py") + text("app/handlers/admin_common.py") + text("app/handlers/admin_core.py") + text("app/handlers/admin_events.py") + text("app/handlers/admin_quests_rewards.py") + text("app/handlers/admin_activities_tasks.py") + text("app/handlers/admin_opportunities.py") + text("app/handlers/admin_moderation.py"))
    assert "user.staff_permissions_json = None" in admin
    assert '"telegram_user_role_change"' in admin
