from pathlib import Path


def _read_version() -> str:
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION.txt").read_text(encoding="utf-8").strip() or "1.17.2"
    except Exception:
        return "1.17.2"


APP_VERSION = _read_version()
