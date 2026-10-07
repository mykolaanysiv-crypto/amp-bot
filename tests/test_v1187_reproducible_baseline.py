from pathlib import Path

from scripts.dependency_lock_check import validate_dependency_locks
from scripts.release_consistency_check import validate_release_consistency

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_v1187_version_and_schema_are_frozen():
    assert read("VERSION.txt").strip() == "1.18.7"
    assert read("VERSION_CHECK.txt").strip() == "1.18.7"
    assert '"1.18.7"' in read("app/version.py")
    assert 'revision = "20260925_0015"' in read("migrations/versions/20260925_0015_quest_qr_on_time.py")


def test_v1187_dependency_locks_are_exact_and_consistent():
    hashes = validate_dependency_locks(ROOT)
    assert set(hashes) == {"requirements.lock", "requirements-dev.lock"}
    assert "cryptography==50.0.2" in read("requirements.lock")
    assert read("requirements.txt").strip().endswith("-r requirements.lock")
    assert read("requirements-dev.txt").strip().endswith("-r requirements-dev.lock")


def test_v1187_release_documentation_gate_passes():
    validate_release_consistency(ROOT)


def test_v1187_ci_security_audit_is_blocking():
    workflow = read(".github/workflows/ci.yml")
    block = workflow[workflow.index("Dependency vulnerability audit"):workflow.index("Installed dependency consistency")]
    assert "pip-audit -r requirements.lock --progress-spinner=off" in block
    assert "continue-on-error" not in block


def test_v1187_runtime_matrix_is_aligned():
    assert "FROM python:3.13-slim" in read("Dockerfile")
    assert "public.ecr.aws/docker/library/postgres:18-alpine" in read("docker-compose.yml")
    assert read(".python-version").strip() == "3.13"
    workflow = read(".github/workflows/ci.yml")
    assert workflow.count("image: public.ecr.aws/docker/library/postgres:18") >= 2


def test_v1187_static_cache_tokens_are_current():
    for name in ("base.html", "login.html", "login_2fa.html"):
        assert "v=1.18.7" in read(f"app/web/templates/{name}")
