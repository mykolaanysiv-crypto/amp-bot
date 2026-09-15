from __future__ import annotations

from pathlib import Path
import ast

from app.version import APP_VERSION


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION.txt").read_text(encoding="utf-8").strip()
    if version != APP_VERSION:
        raise SystemExit(f"VERSION mismatch: VERSION.txt={version!r}, APP_VERSION={APP_VERSION!r}")

    procfile = (root / "Procfile").read_text(encoding="utf-8")
    required = (
        "web: python run_web.py",
        "worker: python run.py",
        "release: python -m scripts.heroku_release",
    )
    missing = [item for item in required if item not in procfile]
    if missing:
        raise SystemExit(f"Procfile preflight failed: missing {missing}")

    if not (root / "alembic.ini").exists() or not list((root / "migrations" / "versions").glob("*.py")):
        raise SystemExit("Alembic preflight failed: migration baseline missing")

    required_files = (
        root / "scripts" / "startup_smoke.py",
        root / "app" / "runtime_health.py",
        root / ".github" / "workflows" / "ci.yml",
    )
    missing_files = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    if missing_files:
        raise SystemExit(f"Production stability files missing: {missing_files}")

    # Refactor guard: a single-dot import inside app.domain_services must point
    # to a real sibling module. Root app modules (donations, settlements,
    # reliability, ...) must use ``..module``. This catches the exact class of
    # regressions that previously escaped compileall and failed only at runtime.
    domain_dir = root / "app" / "domain_services"
    sibling_modules = {path.stem for path in domain_dir.glob("*.py")}
    bad_relative_imports: list[str] = []
    for path in domain_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                sibling = node.module.split(".", 1)[0]
                if sibling not in sibling_modules:
                    bad_relative_imports.append(
                        f"{path.relative_to(root)}:{node.lineno}: from .{node.module} import ..."
                    )
    if bad_relative_imports:
        raise SystemExit(
            "Domain-service import preflight failed; missing sibling module(s): "
            + "; ".join(bad_relative_imports)
        )

    web_source = (root / "app" / "web" / "app.py").read_text(encoding="utf-8")
    for endpoint in ("/health/live", "/health/ready", "/health/dependencies"):
        if endpoint not in web_source:
            raise SystemExit(f"Health preflight failed: {endpoint} missing")
    if "from fastapi.encoders import jsonable_encoder" not in web_source or "JSONResponse(jsonable_encoder(payload)" not in web_source:
        raise SystemExit("Health preflight failed: JSON boundary must encode datetime-safe payloads")

    print(f"Production preflight OK for AMP v{APP_VERSION}")


if __name__ == "__main__":
    main()
