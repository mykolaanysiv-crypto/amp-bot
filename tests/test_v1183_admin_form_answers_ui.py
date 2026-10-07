"""Current admin UX source gates (integration and browser tests run in CI)."""
from pathlib import Path
from sqlalchemy import select, union
from app.model_domains import QuickXPAnswer, QuickXPCompletion

ROOT = Path(__file__).resolve().parents[1]
def read(path): return (ROOT / path).read_text(encoding='utf-8')


def test_quick_xp_answers_restrict_access_and_include_partial_quiz_answers():
    routes = read('app/web/routes/quick_xp.py')
    assert '@router.get("/admin/quick-xp/{challenge_id}/answers"' in routes
    assert 'if r := _guard(request)' in routes
    assert 'select(QuickXPAnswer.user_id)' in routes
    assert 'select(QuickXPCompletion.user_id)' in routes
    assert 'limit(per_page)' in routes and 'per_page = 50' in routes
    template = read('app/web/templates/quick_xp_answers.html')
    assert 'done.answer_text' in template
    assert 'answer.answer_option' in template
    assert 'answer.correct' in template
    assert 'answer.answered_at' in template
    assert 'href="/admin/users/{{ user.id }}"' in template
    assert '/admin/quick-xp/{{ row.id }}/answers' in read('app/web/templates/quick_xp.html')


def test_quick_xp_union_compiles_without_extra_schema():
    result = union(select(QuickXPCompletion.user_id), select(QuickXPAnswer.user_id)).subquery()
    stmt = select(result.c.user_id)
    assert 'quick_xp_completions' in str(stmt)
    assert 'quick_xp_answers' in str(stmt)


def test_forms_preserve_content_and_render_localized_errors():
    source = read('app/web/static/admin_forms.js')
    for token in ('fetch(form.action', 'new FormData(form)', 'response.redirected', 'response.status >= 500',
                  'checkEventDate', 'setCustomValidity', 'amp-form-errors', 'invalid', 'textContent'):
        assert token in source
    assert 'admin_forms.js?v=1.19.0' in read('app/web/templates/base.html')
    assert 'record_field_changes' in read('app/web/event_routes/mutations.py')


def test_visual_consistency_and_spacing():
    css = read('app/web/static/admin.css')
    assert 'max(5px, var(--amp-space, 10px))' in css
    assert '.event-cards-grid{align-items:stretch' in css
    assert '.event-card-v2 .event-card-media{aspect-ratio:16/9' in css
    assert '.event-card-v2 .event-card-actions-v2{margin-top:auto;}' in css
