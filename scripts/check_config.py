from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings

s = get_settings(require_bot_token=False)
print("BOT_TOKEN:", "OK" if s.bot_token else "MISSING")
print("SUPERADMIN_IDS:", sorted(s.superadmin_ids))
print("DATA_DIR:", s.data_dir)
print("DATABASE_URL:", s.database_url)
print("PUBLIC_BASE_URL:", s.public_base_url)
print("SEASON:", s.season_name, s.season_start, s.season_end)
print("WEB_LOGIN (legacy bootstrap):", s.web_admin_username)
print("WEB_PASSWORD (legacy bootstrap):", "PRESENT — remove after DB migration" if s.web_admin_password else "NOT SET — OK after migration")
print("WEB_SESSION_SECRET:", "OK" if len(s.web_session_secret) >= 32 else "DEV/TOO SHORT")
