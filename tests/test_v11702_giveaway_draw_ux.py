from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_draw_route_redirects_expected_business_errors_into_ui():
    web = read("app/web/routes/giveaways.py")
    draw = web.split('@router.post("/admin/giveaways/{giveaway_id}/draw")', 1)[1]
    assert "def _draw_block_reason" in web
    assert "Дедлайн ще не настав" in web
    assert "Щоб провести розіграш зараз" in web
    assert "?notice=draw_blocked#results" in draw
    assert "?notice=draw_success#results" in draw
    assert 'raise HTTPException(status_code=409, detail="Дедлайн ще не настав' not in draw


def test_draw_button_is_gated_and_explains_why():
    template = read("app/web/templates/giveaway_detail.html")
    assert "{% if can_draw %}" in template
    assert "Розіграш поки не можна провести" in template
    assert "{{draw_block_reason}}" in template
    assert "draw_success" in template
    assert "draw_blocked" in template


def test_version_bumped_for_hotfix():
    assert read("VERSION.txt").strip() == "1.17.0.2"
