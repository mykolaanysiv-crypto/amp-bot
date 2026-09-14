from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v191_version_and_cache_buster():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == "1.11.0"
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == "1.11.0"
    base=(ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "/static/admin.css?v=1.11.0" in base


def test_advanced_analytics_metrics_exist():
    text=(ROOT / "app/analytics.py").read_text(encoding="utf-8")
    for key in ["cohort_funnel","retention","engagement_score","activity_heatmap"]:
        assert f'"{key}"' in text
    assert "retention_30_pct" in text
    assert "retention_90_pct" in text
    assert "engagement_average" in text
    assert "heatmap_matrix" in text


def test_heatmap_rendering_web_and_exports():
    analytics=(ROOT / "app/analytics.py").read_text(encoding="utf-8")
    tpl=(ROOT / "app/web/templates/analytics.html").read_text(encoding="utf-8")
    detail=(ROOT / "app/web/templates/analytics_detail.html").read_text(encoding="utf-8")
    assert 'metric["kind"] == "heatmap"' in analytics
    assert "analytics-heatmap" in tpl
    assert "analytics-heatmap" in detail
    assert "ColorScaleRule" in analytics
    assert "imshow(matrix" in analytics


def test_report_pdf_is_paginated_without_silent_truncation():
    reports=(ROOT / "app/reports.py").read_text(encoding="utf-8")
    assert "for idx in range(0,len(cards),12)" in reports
    assert "for page_no,start in enumerate(range(0,len(event_rows),20),1)" in reports
    assert "[:25]" not in reports
    assert "all_items[i:i+15]" in reports
    assert "break_long_words=False" in reports
    assert "Розширена аналітика" in reports


def test_notification_status_and_analytics_layout_polish():
    css=(ROOT / "app/web/static/admin.css").read_text(encoding="utf-8")
    tpl=(ROOT / "app/web/templates/notifications.html").read_text(encoding="utf-8")
    assert "grid-template-columns:repeat(4,minmax(0,1fr))!important" in css
    assert "word-break:keep-all!important" in css
    assert 'class="notification-table"' in tpl
    assert 'class="notification-status"' in tpl
