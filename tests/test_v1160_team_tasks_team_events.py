from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_team_task_model_and_migration_exist():
    model = read("app/model_domains/ambassadors.py")
    migration = read("migrations/versions/20260919_0006_team_tasks_team_events.py")
    assert 'class TeamTask(Base)' in model
    assert '__tablename__ = "team_tasks"' in model
    assert 'xp_awarded_at' in model
    assert 'revision: str = "20260919_0006"' in migration
    assert 'down_revision: Union[str, None] = "20260918_0005"' in migration
    assert 'access_scope' in migration


def test_team_task_report_is_required_before_xp_approval():
    web = read("app/web/routes/ambassadors.py")
    tg = read("app/handlers/ambassadors.py")
    assert 'task.status != "submitted" or not task.report_text.strip()' in web
    assert 'task.xp_awarded_at is None' in web
    assert 'category="team_task"' in web
    assert 'TeamTaskReportState.report_text' in tg
    assert 'task.status = "submitted"' in tg


def test_team_roles_have_cabinet_and_restricted_events():
    keyboards = read("app/keyboards.py")
    events = read("app/handlers/events.py")
    assert 'UserRole.COORDINATOR.value' in keyboards
    assert 'Кабінет команди АМП' in keyboards
    assert 'nav:events:general' in events
    assert 'nav:events:team' in events
    assert 'Event.access_scope == scope' in events
    assert 'role in AMP_TEAM_ROLES' in events


def test_private_team_events_have_no_public_share_page():
    public = read("app/web/event_routes/public.py")
    overview = read("app/web/event_routes/overview.py")
    assert 'access_scope", "general") == "team"' in public
    assert 'getattr(event, "access_scope", "general") == "general"' in overview


def test_opportunity_share_button_does_not_embed_json_inside_html_attribute():
    template = read("app/web/templates/opportunity_detail.html")
    assert 'data-share-title="{{item.title|e}}"' in template
    assert 'onclick="shareOpportunity(this)"' in template
    assert 'title:{{item.title|tojson}}' not in template


def test_edit_controls_use_shared_class():
    expected = [
        "app/web/templates/events.html",
        "app/web/templates/tasks.html",
        "app/web/templates/quests.html",
        "app/web/templates/activities.html",
        "app/web/templates/goals.html",
        "app/web/templates/rewards.html",
        "app/web/templates/badges.html",
        "app/web/templates/opportunity_detail.html",
    ]
    for path in expected:
        assert "edit-action-button" in read(path), path
