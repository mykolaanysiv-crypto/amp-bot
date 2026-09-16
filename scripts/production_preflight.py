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

    # v1.13.0.2 startup-import guard: every explicit relative module import
    # inside app/ must resolve to a real Python module/package.  This catches
    # package-depth mistakes introduced while splitting a monolithic module,
    # e.g. ``app.handlers.start_flow`` accidentally importing ``..time_utils``
    # (which resolves to the nonexistent ``app.handlers.time_utils``) instead
    # of ``...time_utils``.  compileall cannot catch this class of runtime error.
    unresolved_relative_imports: list[str] = []
    app_dir = root / "app"
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_module = path.relative_to(root).with_suffix("")
        module_parts = list(rel_module.parts)
        package_parts = module_parts[:-1]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level or not node.module:
                continue
            up = node.level - 1
            if up > len(package_parts):
                unresolved_relative_imports.append(
                    f"{path.relative_to(root)}:{node.lineno}: relative import escapes package root"
                )
                continue
            target_parts = package_parts[: len(package_parts) - up] + node.module.split(".")
            module_file = root.joinpath(*target_parts).with_suffix(".py")
            package_init = root.joinpath(*target_parts) / "__init__.py"
            if not module_file.exists() and not package_init.exists():
                unresolved_relative_imports.append(
                    f"{path.relative_to(root)}:{node.lineno}: from {'.' * node.level}{node.module} import ... -> "
                    f"{'.'.join(target_parts)}"
                )
    if unresolved_relative_imports:
        raise SystemExit(
            "Startup import preflight failed: unresolved relative module import(s): "
            + "; ".join(unresolved_relative_imports)
        )


    # v1.12.2 hardening gates: one Clock boundary, no deprecated utcnow calls,
    # no silent broad-exception swallowing, and structured error context.
    time_source = (root / "app" / "time_utils.py").read_text(encoding="utf-8")
    if "class Clock" not in time_source or "clock = Clock()" not in time_source or "def now_utc" not in time_source:
        raise SystemExit("Time preflight failed: canonical Clock helper missing")

    direct_time_hits: list[str] = []
    silent_exception_hits: list[str] = []
    allowed_time_source = root / "app" / "time_utils.py"
    for scan_root in (root / "app", root / "scripts"):
        for path in scan_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            if path != allowed_time_source and path.name != "production_preflight.py":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        if (node.value.id, node.attr) in {
                            ("datetime", "utcnow"),
                            ("datetime", "now"),
                            ("date", "today"),
                        }:
                            direct_time_hits.append(f"{path.relative_to(root)}:{node.lineno}:{node.value.id}.{node.attr}")
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    silent_exception_hits.append(f"{path.relative_to(root)}:{node.lineno}")
    if direct_time_hits:
        raise SystemExit("Time preflight failed: direct wall-clock API outside Clock: " + ", ".join(sorted(set(direct_time_hits))))
    if silent_exception_hits:
        raise SystemExit("Error preflight failed: silent broad exceptions at " + ", ".join(silent_exception_hits))

    observability_source = (root / "app" / "observability.py").read_text(encoding="utf-8")
    for token in ("error_code", "context", "def log_extra"):
        if token not in observability_source:
            raise SystemExit(f"Observability preflight failed: {token} missing")

    # v1.13.0 architecture completion gates.  The old monolith modules remain
    # only as explicit compatibility facades; canonical implementation lives in
    # focused packages/modules.
    factory_source = (root / "app" / "web" / "factory.py").read_text(encoding="utf-8")
    web_facade_source = (root / "app" / "web" / "app.py").read_text(encoding="utf-8")
    run_web_source = (root / "run_web.py").read_text(encoding="utf-8")
    if "def create_app()" not in factory_source:
        raise SystemExit("Architecture preflight failed: app.web.factory.create_app missing")
    if "from .factory import create_app" not in web_facade_source or "app = create_app()" not in web_facade_source:
        raise SystemExit("Architecture preflight failed: app.web.app compatibility facade is not factory-backed")
    if '"app.web.factory:create_app"' not in run_web_source or "factory=True" not in run_web_source:
        raise SystemExit("Architecture preflight failed: web runtime does not start through create_app factory mode")

    health_source = (root / "app" / "web" / "health_routes.py").read_text(encoding="utf-8")
    for endpoint in ("/health/live", "/health/ready", "/health/dependencies"):
        if endpoint not in health_source:
            raise SystemExit(f"Health preflight failed: {endpoint} missing")
    if "from fastapi.encoders import jsonable_encoder" not in health_source or "JSONResponse(jsonable_encoder(payload)" not in health_source:
        raise SystemExit("Health preflight failed: JSON boundary must encode datetime-safe payloads")

    architecture_paths = (
        root / "app" / "web" / "dependencies.py",
        root / "app" / "web" / "event_routes",
        root / "app" / "analytics_modules",
        root / "app" / "reporting",
        root / "app" / "model_domains",
        root / "app" / "handlers" / "start_flow",
        root / "app" / "jobs",
        root / "app" / "bot_runtime.py",
    )
    missing_architecture = [str(path.relative_to(root)) for path in architecture_paths if not path.exists()]
    if missing_architecture:
        raise SystemExit(f"Architecture preflight failed: missing split components {missing_architecture}")

    facade_limits = {
        root / "app" / "web" / "app.py": 80,
        root / "app" / "analytics.py": 80,
        root / "app" / "reports.py": 80,
        root / "app" / "web" / "routes" / "events.py": 80,
        root / "app" / "models.py": 180,
        root / "app" / "handlers" / "start.py": 80,
        root / "app" / "main.py": 140,
    }
    oversized_facades: list[str] = []
    for path, max_lines in facade_limits.items():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            oversized_facades.append(f"{path.relative_to(root)}={line_count}>{max_lines}")
    if oversized_facades:
        raise SystemExit("Architecture preflight failed: oversized compatibility/composition modules: " + ", ".join(oversized_facades))

    wildcard_imports: list[str] = []
    for path in (root / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                wildcard_imports.append(f"{path.relative_to(root)}:{node.lineno}")
    if wildcard_imports:
        raise SystemExit("Architecture preflight failed: wildcard imports remain at " + ", ".join(wildcard_imports))

    # Release asset-cache guard: historical regression tests key static assets
    # to VERSION.txt.  A patch release must update the three public/admin login
    # templates together or browsers can keep stale CSS/logo assets.
    cache_token = f"?v={APP_VERSION}"
    for template_rel in (
        "app/web/templates/base.html",
        "app/web/templates/login.html",
        "app/web/templates/login_2fa.html",
    ):
        template_source = (root / template_rel).read_text(encoding="utf-8")
        if cache_token not in template_source:
            raise SystemExit(
                f"Release asset preflight failed: {template_rel} does not use current cache token {cache_token}"
            )

    # Schema continuity: the architecture release must not silently alter the
    # v1.12.1.7/v1.12.2 production schema or Alembic head.
    models_source = (root / "app" / "models.py").read_text(encoding="utf-8")
    if "model_domains" not in models_source or "Compatibility facade" not in models_source:
        raise SystemExit("Architecture preflight failed: app.models is not the explicit compatibility facade")
    migration_source = (root / "migrations" / "versions" / "20260915_0002_content_views.py").read_text(encoding="utf-8")
    if 'revision: str = "20260915_0002"' not in migration_source:
        raise SystemExit("Alembic preflight failed: expected production head 20260915_0002 missing")

    print(f"Production preflight OK for AMP v{APP_VERSION}")


if __name__ == "__main__":
    main()
