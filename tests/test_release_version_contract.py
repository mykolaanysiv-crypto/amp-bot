"""Release guard that does not need hand-edited version strings."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def test_release_sources_consistent():
    expected = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?", expected)
    assert (ROOT / "VERSION_CHECK.txt").read_text(encoding="utf-8").strip() == expected
    from app.version import APP_VERSION
    assert APP_VERSION == expected

def test_template_cache_tokens_refer_to_current_version():
    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    templates = ROOT / "app/web/templates"
    found = 0
    for path in templates.glob("*.html"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:src|href)=[\"'][^\"']*?/static/[^\"']*?\?v=([0-9]+\.[0-9]+\.[0-9]+)[^\"']*[\"']", source):
            found += 1
            assert match.group(1) == version, f"Outdated cache key in {path}: {match.group(1)} != {version}"
    assert found > 0
