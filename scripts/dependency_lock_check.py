from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s]+$")
NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")


def _active_lines(path: Path) -> list[str]:
    rows: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line)
    return rows


def _name(spec: str) -> str:
    match = NAME_RE.match(spec)
    if not match:
        raise SystemExit(f"Cannot parse dependency spec: {spec}")
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def _intent_names(path: Path) -> set[str]:
    return {_name(line) for line in _active_lines(path) if not line.startswith("-r ")}


def _locked_names(path: Path) -> set[str]:
    names: set[str] = set()
    for line in _active_lines(path):
        if line.startswith("-r "):
            continue
        if not PIN_RE.fullmatch(line):
            raise SystemExit(f"Dependency lock is not exact: {path.name}: {line}")
        names.add(_name(line))
    return names


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate_dependency_locks(root: Path = ROOT) -> dict[str, str]:
    expected_wrappers = {
        "requirements.txt": ["-r requirements.lock"],
        "requirements-dev.txt": ["-r requirements-dev.lock"],
    }
    for name, expected in expected_wrappers.items():
        actual = _active_lines(root / name)
        if actual != expected:
            raise SystemExit(f"{name} must be a stable lock wrapper: expected {expected!r}, got {actual!r}")

    prod_intent = _intent_names(root / "requirements.in")
    prod_locked = _locked_names(root / "requirements.lock")
    if prod_intent != prod_locked:
        raise SystemExit(
            "Production dependency lock mismatch: "
            f"missing={sorted(prod_intent - prod_locked)}, extra={sorted(prod_locked - prod_intent)}"
        )

    dev_rows = _active_lines(root / "requirements-dev.lock")
    if not dev_rows or dev_rows[0] != "-r requirements.lock":
        raise SystemExit("requirements-dev.lock must include -r requirements.lock first")
    dev_intent = _intent_names(root / "requirements-dev.in") - prod_intent
    dev_locked = _locked_names(root / "requirements-dev.lock")
    if dev_intent != dev_locked:
        raise SystemExit(
            "Development dependency lock mismatch: "
            f"missing={sorted(dev_intent - dev_locked)}, extra={sorted(dev_locked - dev_intent)}"
        )

    crypto = [line for line in _active_lines(root / "requirements.lock") if _name(line) == "cryptography"]
    if crypto != ["cryptography==50.0.2"]:
        raise SystemExit(f"Security dependency lock mismatch: expected cryptography==50.0.2, got {crypto!r}")

    return {
        "requirements.lock": file_sha256(root / "requirements.lock"),
        "requirements-dev.lock": file_sha256(root / "requirements-dev.lock"),
    }


def main() -> None:
    hashes = validate_dependency_locks()
    print("Dependency lock consistency PASS")
    for name, digest in hashes.items():
        print(f"{name}: sha256={digest}")


if __name__ == "__main__":
    main()
