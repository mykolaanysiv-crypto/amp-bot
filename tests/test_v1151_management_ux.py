from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_release_version_and_cache_tokens_are_synced():
    version = read("VERSION.txt").strip()
    assert tuple(map(int, version.split("."))) >= (1, 15, 1)
    assert read("VERSION_CHECK.txt").strip() == version
    for template in ("app/web/templates/base.html", "app/web/templates/login.html", "app/web/templates/login_2fa.html"):
        assert f"?v={version}" in read(template)


def test_survey_audience_picker_is_checkbox_search_ui():
    for template in ("app/web/templates/surveys.html", "app/web/templates/survey_detail.html"):
        src = read(template)
        assert "survey-user-picker" in src
        assert "Пошук учасника" in src
        assert "Обрати показаних" in src
        assert "surveyAudienceCount" in src
        assert 'type="checkbox" name="audience_user_ids"' in src
        assert "Ctrl/Cmd + клік" not in src
    css = read("app/web/static/admin.css")
    assert ".survey-event-picker" in css
    assert ".survey-audience-panel" in css


def test_rewards_and_badges_have_safe_durable_delete_actions():
    route = read("app/web/routes/gamification.py")
    rewards = read("app/web/templates/rewards.html")
    badges = read("app/web/templates/badges.html")
    seeds = read("app/badge_seeds.py")
    model = read("app/model_domains/gamification.py")
    migration = read("migrations/versions/20260918_0005_badge_seed_keys.py")
    core_seed = read("app/domain_services/gamification.py")
    donation_seed = read("app/donations.py")
    assert '@router.post("/admin/rewards/{reward_id}/delete")' in route
    assert "web_reward_delete_blocked_history" in route
    assert 'action="/admin/rewards/{{r.id}}/delete"' in rewards
    assert '@router.post("/admin/badges/{badge_id}/delete")' in route
    assert "mark_badge_seed_deleted(session, badge.seed_key)" in route
    assert "delete(UserBadge)" in route
    assert 'action="/admin/badges/{{b.id}}/delete"' in badges
    assert "система не створить його повторно" in badges
    assert "BADGE_DELETE_PREFIX" in seeds and "badge_seed_is_deleted" in seeds
    assert "seed_key:" in model
    assert 'revision: str = "20260918_0005"' in migration
    assert 'down_revision: Union[str, None] = "20260918_0004"' in migration
    assert "badge_seed_is_deleted(session, seed_key)" in core_seed
    assert "badge_seed_is_deleted(session, seed_key)" in donation_seed


def test_opportunity_board_is_compact_and_detail_page_carries_full_content():
    board = read("app/web/templates/opportunities.html")
    detail = read("app/web/templates/opportunity_detail.html")
    route = read("app/web/routes/opportunities.py")
    public = read("app/web/templates/opportunity_public.html")
    css = read("app/web/static/admin.css")
    assert 'href="/admin/opportunities/{{item.id}}">👁 Детально' in board
    assert "{{item.description or 'Без опису.'}}" not in board
    assert "opportunity-board" in board and "opportunity-card-actions" in board
    assert '@router.get("/admin/opportunities/{opportunity_id}"' in route
    assert '@router.get("/opportunity/{opportunity_id}"' in route
    for token in ("Аналітика можливості", "Поділитися можливістю", "КЕРУВАННЯ МОЖЛИВІСТЮ", "Видалити можливість", "Зацікавлені учасники", "Персональні збіги"):
        assert token in detail
    assert "share_url" in route and "interest_rate" in route and "avg_score" in route
    assert "Долучитися / дізнатися більше" in public
    assert ".opportunity-board>.opportunity-card" in css
    assert "min-height:430px" in css


def test_opportunity_management_has_publish_hide_and_match_refresh():
    route = read("app/web/routes/opportunities.py")
    detail = read("app/web/templates/opportunity_detail.html")
    assert '@router.post("/admin/opportunities/{opportunity_id}/toggle")' in route
    assert '@router.post("/admin/opportunities/{opportunity_id}/refresh-matches")' in route
    assert "web_opportunity_matches_refresh" in route
    assert "Приховати можливість" in detail
    assert "Опублікувати знову" in detail
    assert "Оновити персональні збіги" in detail
