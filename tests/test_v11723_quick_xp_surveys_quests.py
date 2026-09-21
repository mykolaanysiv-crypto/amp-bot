from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v11723_version_and_migration():
    version = read("VERSION.txt").strip()
    assert version == "1.17.2.3"
    assert read("VERSION_CHECK.txt").strip() == version
    migration = read("migrations/versions/20260921_0012_quick_xp_multi_question.py")
    assert 'revision: str = "20260921_0012"' in migration
    assert 'down_revision: Union[str, None] = "20260921_0011"' in migration
    assert '"quick_xp_questions"' in migration
    assert '"quick_xp_answers"' in migration
    assert 'uq_quick_xp_question_user' in migration


def test_quick_xp_is_dynamic_and_has_multi_question_scoring():
    template = read("app/web/templates/quick_xp.html")
    routes = read("app/web/routes/quick_xp.py")
    handler = read("app/handlers/quick_xp.py")
    service = read("app/quick_xp.py")
    runtime = read("app/runtime_config.py")
    model = read("app/model_domains/engagement.py")
    assert 'data-kind-panel="quiz"' in template
    assert 'data-kind-panel="video"' in template
    assert 'data-kind-panel="poll"' in template
    assert 'data-kind-panel="comment"' in template
    assert 'data-add-quiz-question' in template
    assert 'quiz_question_xp' in template
    assert 'Порядок<input' not in template
    assert 'quick_xp.weekly_cap' in runtime and '30, 1, 500' in runtime
    assert 'class QuickXPQuestion' in model
    assert 'class QuickXPAnswer' in model
    assert 'answer_quiz_question' in service
    assert 'quickxp_quiz:' in handler
    assert '/questions/{question_id}/move' in routes


def test_surveys_have_separate_identity_question_edit_and_reorder():
    routes = read("app/web/routes/surveys.py")
    template = read("app/web/templates/survey_detail.html")
    assert '/admin/surveys/{survey_id}/identity' in routes
    assert '/questions/{question_id}/update' in routes
    assert '/questions/{question_id}/move' in routes
    assert '✏️ Редагувати' in template
    assert 'name="direction" value="up"' in template
    assert 'name="direction" value="down"' in template
    assert 'id="survey-identity"' in template
    assert 'id="survey-settings"' in template


def test_quest_cards_use_equal_height_geometry_and_detail_action():
    css = read("app/web/static/admin.css")
    template = read("app/web/templates/quests.html")
    assert '.work-cards-grid{align-items:stretch!important}' in css
    assert '.work-cards-grid>.entity-card-v2{height:100%!important}' in css
    assert '.quest-card-v2 .entity-card-media{height:230px' in css
    assert 'href="/admin/quests/{{q.id}}">👁 Детально</a>' in template
    assert 'edit-action-button' in template
