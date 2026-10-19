from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "web" / "static"
PARTS = ("legacy.css", "tokens.css", "base.css", "layout.css", "components.css", "experience.css", "interaction.css", "refinement.css", "utilities.css", "polish.css", "product_experience.css", "ux22_modals.css", "ui_refinement_1221.css", "ux_release_1224.css", "ux_hotfix_operations.css", "design_system_v2.css")
CANONICAL_PARTS = ("styles/components/controls.css", "styles/components/navigation.css", "styles/components/tables.css", "styles/themes/dark.css", "styles/responsive.css")


def bundle_text() -> str:
    chunks = ["/* AUTO-BUNDLED by scripts/build_admin_css.py — edit source modules, not this header. */\n"]
    for name in (*PARTS, *CANONICAL_PARTS):
        path = STATIC / name
        chunks.append(f"\n/* ===== {name} ===== */\n")
        chunks.append(path.read_text(encoding="utf-8").rstrip() + "\n")
    return "".join(chunks)


def build() -> str:
    bundled = bundle_text()
    (STATIC / "admin.css").write_text(bundled, encoding="utf-8")
    return bundled


def check() -> bool:
    target = STATIC / "admin.css"
    return target.exists() and target.read_text(encoding="utf-8") == bundle_text()


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        if not check():
            print("admin.css is stale: run python -m scripts.build_admin_css", file=sys.stderr)
            raise SystemExit(1)
        print("admin.css bundle is reproducible: PASS")
    else:
        build()
        print("admin.css bundle rebuilt")
