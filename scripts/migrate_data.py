from __future__ import annotations

from app.time_utils import clock

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

if len(sys.argv) < 2:
    raise SystemExit("Використання: python scripts/migrate_data.py /шлях/до/старої_версії")

old_project = Path(sys.argv[1]).expanduser().resolve()
old_data = old_project / "data"
source_db = old_data / "amp_bot.db"
if not source_db.exists():
    raise SystemExit(f"Не знайдено стару базу: {source_db}")

target = Path(os.getenv("AMP_DATA_DIR", "~/AMP_Bot_Data")).expanduser().resolve()
target.mkdir(parents=True, exist_ok=True)
(target / "uploads").mkdir(parents=True, exist_ok=True)
(target / "backups").mkdir(parents=True, exist_ok=True)

target_db = target / "amp_bot.db"
if target_db.exists():
    backup = target / "backups" / f"before_migration_{clock.now_local().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(target_db, backup)
    print(f"Створено резервну копію поточної бази: {backup}")

shutil.copy2(source_db, target_db)
source_uploads = old_data / "uploads"
if source_uploads.exists():
    shutil.copytree(source_uploads, target / "uploads", dirs_exist_ok=True)

print(f"✅ Базу перенесено: {target_db}")
print(f"✅ Фото/файли: {target / 'uploads'}")
print("Надалі нові версії використовуватимуть цю саму постійну папку.")
