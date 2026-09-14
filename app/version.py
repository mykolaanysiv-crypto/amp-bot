from pathlib import Path


def _read_version() -> str:
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION.txt").read_text(encoding="utf-8").strip() or "1.10.3"
    except Exception:
        return "1.10.3"


APP_VERSION = _read_version()
