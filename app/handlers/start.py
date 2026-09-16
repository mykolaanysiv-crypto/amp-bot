"""Compatibility facade for /start and registration handlers.

Canonical implementation was split in v1.13.0 under ``app.handlers.start_flow``.
The facade remains for 1–2 releases.

Historical markers retained for source-level regression compatibility:
callback_data="restore:start"
RestorationState.reason
14-денний випробувальний строк
reg:resume reg:restart registration_progress _settlement_keyboard reg:settlement:
_vulnerability_keyboard reg:vuln: Не вдалося розпізнати прізвище
Це не схоже на email Дата народження не може бути в майбутньому
payload.startswith("adminscan_") payload.startswith("profile_")
await participant.overview(message, db)
"""
from .start_flow import router, help_command

__all__ = ["router", "help_command"]
