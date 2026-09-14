from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_webapp_init_data(init_data: str, bot_token: str, *, max_age_seconds: int = 3600) -> dict | None:
    """Validate Telegram Mini App initData and return the authenticated user.

    Telegram signs initData with HMAC-SHA256.  We verify the signature and keep
    a short authentication window so a copied payload cannot be reused forever.
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
        supplied_hash = str(pairs.pop("hash", ""))
        if not supplied_hash:
            return None
        auth_date = int(pairs.get("auth_date") or 0)
        now = int(time.time())
        if auth_date <= 0 or auth_date > now + 60 or now - auth_date > max(60, int(max_age_seconds)):
            return None
        data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, supplied_hash):
            return None
        user = json.loads(pairs.get("user") or "{}")
        if not isinstance(user, dict) or not int(user.get("id") or 0):
            return None
        return user
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
