from datetime import date, datetime, timedelta
from pathlib import Path

from app.models import Base, Opportunity, OpportunityMatch, Season, User
from app.opportunity_matching import match_opportunity, set_user_interests
from tests.source_layout import main_source

ROOT = Path(__file__).resolve().parents[1]


def test_v192_version_schema_and_cache():
    version = (ROOT / "VERSION.txt").read_text().strip()
    assert version
    assert (ROOT / "VERSION_CHECK.txt").read_text().strip() == version
    assert len(Base.metadata.tables) >= 53
    assert "opportunity_matches" in Base.metadata.tables
    assert {"finalized_at", "history_json"} <= {c.name for c in Season.__table__.columns}
    assert "opportunity_interests_json" in {c.name for c in User.__table__.columns}
    assert "target_settlements" in {c.name for c in Opportunity.__table__.columns}
    assert f"/static/admin.css?v={(ROOT / 'VERSION.txt').read_text().strip()}" in (ROOT / "app/web/templates/base.html").read_text()


def test_matching_uses_explicit_interests_age_settlement_format_deadline_not_vulnerability():
    user = User(tg_id=1, full_name="Тест Учасник", settlement="Анисів", birth_date=date.today().replace(year=date.today().year-20), vulnerability_categories='["anything"]')
    set_user_interests(user, ["IT", "Освіта"])
    item = Opportunity(title="IT школа", kind="Освіта", direction="IT", format="Офлайн", age_min=18, age_max=30, target_settlements="Анисів, Іванівка", deadline=datetime.utcnow()+timedelta(days=10), active=True)
    result = match_opportunity(user, item)
    assert result is not None and result[0] >= 70
    score = result[0]
    user.vulnerability_categories = '["changed"]'
    assert match_opportunity(user, item)[0] == score
    item.age_max = 19
    assert match_opportunity(user, item) is None


def test_matching_requires_explicit_interest_for_auto_notification():
    user = User(tg_id=2, full_name="Без інтересів", settlement="Іванівка", birth_date=date(2000,1,1))
    item = Opportunity(title="Грант", kind="Грант", direction="Гранти", format="Онлайн", active=True)
    assert match_opportunity(user, item) is None


def test_telegram_and_web_smart_opportunity_ui_present():
    participant = "\n".join((ROOT / "app/handlers" / name).read_text(encoding="utf-8") for name in ['participant.py', 'participant_common.py', 'participant_home.py', 'participant_requests.py', 'participant_opportunities.py', 'participant_activities.py', 'participant_tasks.py'])
    matching = (ROOT / "app/opportunity_matching.py").read_text()
    route = (ROOT / "app/web/routes/opportunities.py").read_text()
    tpl = (ROOT / "app/web/templates/opportunities.html").read_text()
    assert "⚙️ Мої інтереси" in participant
    for name in ["Волонтерство", "Освіта", "Гранти", "Обміни", "Підприємництво", "Культура", "Спорт", "IT", "Медіа"]:
        assert name in matching
    assert "vulnerability_categories" not in matching
    assert "refresh_matches_for_opportunity" in route
    assert "target_settlements" in route and "target_settlements" in tpl
    assert "match_counts" in route


def test_smart_opportunities_scheduler_and_notification_digest():
    main = main_source()
    matching = (ROOT / "app/opportunity_matching.py").read_text()
    assert "_smart_opportunities_scheduler" in main
    assert "queue_pending_match_digests" in main
    assert "Для тебе знайдено" in matching
    assert 'dedupe_key=key' in matching
    assert 'button_text="🌍 Відкрити можливості"' in matching


def test_season_history_snapshot_and_profile_history():
    season = (ROOT / "app/season_history.py").read_text()
    routes = (ROOT / "app/web/routes/gamification.py").read_text()
    seasons_tpl = (ROOT / "app/web/templates/seasons.html").read_text()
    detail_tpl = (ROOT / "app/web/templates/season_detail.html").read_text()
    participant = (ROOT / "app/handlers/v11.py").read_text()
    profile = (ROOT / "app/web/templates/user_detail.html").read_text()
    for token in ["top3", "league_winners", '"xp"', '"streak"', '"volunteer_hours"', '"badges"']:
        assert token in season
    assert "await finalize_season(session,s)" in routes
    assert '/admin/seasons/{season_id}' in routes
    assert "П'єдестал сезону" in detail_tpl
    assert "Переможці ліг" in detail_tpl
    assert "Бейджі сезону" in detail_tpl
    assert "🕰 Історія сезонів" in participant
    assert 'data-tab="seasons"' in profile
    assert "СЕЗОНИ ТА ІСТОРІЯ" in seasons_tpl


def test_startup_does_not_resurrect_finalized_season():
    services = (ROOT / "app/domain_services/gamification.py").read_text()
    assert "without re-activating archived history" in services
    assert "if not season.finalized_at" in services
    assert "season.active = True" in services
