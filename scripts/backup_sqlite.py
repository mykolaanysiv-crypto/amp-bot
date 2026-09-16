from __future__ import annotations

from app.time_utils import clock

import os
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
root = Path(os.getenv("AMP_DATA_DIR", "~/AMP_Bot_Data")).expanduser().resolve()
src = root / "amp_bot.db"
if not src.exists():
    raise SystemExit(f"Базу не знайдено: {src}")
out_dir = root / "backups"
out_dir.mkdir(parents=True, exist_ok=True)
dst = out_dir / f"amp_bot_{clock.now_local().strftime('%Y%m%d_%H%M%S')}.db"
shutil.copy2(src, dst)
print(f"✅ Резервна копія БД: {dst}")
