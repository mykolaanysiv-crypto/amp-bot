"""Compatibility facade for admin Telegram handlers without wildcard imports."""
from .admin_common import router
from .admin_core import admin_panel
# Import focused modules for decorator registration on the shared router.
from . import admin_events as _admin_events
from . import admin_quests_rewards as _admin_quests_rewards
from . import admin_activities_tasks as _admin_activities_tasks
from . import admin_opportunities as _admin_opportunities
from . import admin_moderation as _admin_moderation

__all__ = ["router", "admin_panel"]
