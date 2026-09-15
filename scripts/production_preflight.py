from __future__ import annotations

from pathlib import Path

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

    web_source = (root / "app" / "web" / "app.py").read_text(encoding="utf-8")
    for endpoint in ("/health/live", "/health/ready", "/health/dependencies"):
        if endpoint not in web_source:
            raise SystemExit(f"Health preflight failed: {endpoint} missing")

    print(f"Production preflight OK for AMP v{APP_VERSION}")


if __name__ == "__main__":
    main()
