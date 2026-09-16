from __future__ import annotations

from app.time_utils import clock

import os
import zipfile
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
root = Path(os.getenv("AMP_DATA_DIR", "~/AMP_Bot_Data")).expanduser().resolve()
if not root.exists():
    raise SystemExit(f"Каталог даних не знайдено: {root}")
backup_dir = root / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
out = backup_dir / f"AMP_full_backup_{clock.now_local().strftime('%Y%m%d_%H%M%S')}.zip"
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for path in root.rglob("*"):
        if not path.is_file() or backup_dir in path.parents:
            continue
        z.write(path, path.relative_to(root))
print(f"✅ Повна резервна копія: {out}")
