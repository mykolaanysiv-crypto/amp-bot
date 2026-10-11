"""Static assertions for safe survey editing / modal lifetime (not end-to-end)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/static/ux22_modals.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/web/static/ux22_modals.css").read_text(encoding="utf-8")

def test_survey_question_edit_dialog_uses_existing_form():
    assert "details.survey-question-edit-details" in JS
    assert "body.appendChild(node)" in JS
    assert "marker.parentNode.insertBefore(node,marker.nextSibling)" in JS

def test_dialog_handles_showmodal_exception_without_orphaning_form():
    assert "try { dialog.showModal(); } catch (error) { restore(); throw error; }" in JS

def test_dialog_responsive_question_edit():
    assert ".ux22-dialog:has(.survey-question-edit-details)" in CSS
    assert "max-width:680px" in CSS
