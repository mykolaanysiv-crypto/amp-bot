"""Static regression checks for modal UX follow-up (not E2E)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'app/web/static/ux22_modals.js').read_text(encoding='utf-8')
CSS = (ROOT / 'app/web/static/ux22_modals.css').read_text(encoding='utf-8')

def test_submit_is_validated_before_pending_state():
    assert 'form.checkValidity()' in JS
    assert 'if (pendingSubmit)' in JS
    assert "submitter.setAttribute('aria-disabled', 'true')" in JS
    assert 'submitter.disabled = true' not in JS

def test_restores_dialog_state_on_close():
    assert 'pendingSubmit=false' in JS
    assert "removeAttribute('aria-disabled')" in JS
    assert 'marker.parentNode.insertBefore(node,marker.nextSibling)' in JS

def test_keyboard_focus_and_reduced_motion():
    assert 'opener.focus({preventScroll:true})' in JS
    assert ':focus-visible' in CSS
    assert 'prefers-reduced-motion' in CSS
