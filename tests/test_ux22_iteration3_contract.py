"""Static UX regression checks — iteration 3; not browser E2E."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/static/ux22_modals.js").read_text(encoding="utf-8")
CSS = (ROOT / "app/web/static/ux22_modals.css").read_text(encoding="utf-8")

def test_all_create_forms_share_one_collapsed_selector():
    assert "source.dataset.ux22Collapsed = 'true'" in JS
    assert '[data-ux22-collapsed="true"] {display:none!important}' in CSS

def test_node_recovers_collapsed_state_after_modal_close():
    assert "node.dataset.ux22CollapsedInitially" in JS
    assert "delete node.dataset.ux22Collapsed;" in JS
    assert "node.dataset.ux22Collapsed = 'true'" in JS

def test_original_form_is_moved_not_cloned():
    assert 'body.appendChild(node)' in JS
    assert 'marker.parentNode.insertBefore(node,marker.nextSibling)' in JS
    assert 'cloneNode(' not in JS
