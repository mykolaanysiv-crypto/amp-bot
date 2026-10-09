from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"
PARTS = ("legacy.css", "tokens.css", "base.css", "layout.css", "components.css", "utilities.css")


def build() -> str:
    chunks = ["/* AUTO-BUNDLED by scripts/build_admin_css.py — edit source modules, not this header. */\n"]
    for name in PARTS:
        path = STATIC / name
        chunks.append(f"\n/* ===== {name} ===== */\n")
        chunks.append(path.read_text(encoding="utf-8").rstrip() + "\n")
    bundled = "".join(chunks)
    (STATIC / "admin.css").write_text(bundled, encoding="utf-8")
    return bundled


if __name__ == "__main__":
    build()
    print("admin.css bundle rebuilt")
