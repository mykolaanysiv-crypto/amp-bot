from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "app" / "web" / "routes"


def _is_fastapi_body_default(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"Form", "File", "Body"}


def test_no_leading_underscore_fastapi_body_parameters():
    bad = []
    for path in ROUTES.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            args = fn.args.args
            defaults = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
            for arg, default in zip(args, defaults):
                if arg.arg.startswith("_") and _is_fastapi_body_default(default):
                    bad.append(f"{path.name}:{fn.lineno}:{fn.name}:{arg.arg}")
    assert not bad, "FastAPI/Pydantic v2 startup-risk body params: " + ", ".join(bad)


def test_event_scanner_has_no_csrf_body_parameter():
    source = (ROUTES / "events.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    scanner = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "event_web_scanner")
    names = [a.arg for a in scanner.args.args]
    assert "_csrf" not in names
    assert names[:4] == ["request", "event_id", "code", "action"]


def test_csrf_still_checked_by_middleware():
    source = (ROOT / "app" / "web" / "security_middleware.py").read_text(encoding="utf-8")
    assert 'form.get("_csrf")' in source
    assert 'compare_digest(expected, submitted)' in source
