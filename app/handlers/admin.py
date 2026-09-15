"""Compatibility facade for split admin handlers (v1.12)."""
from .admin_common import router
from .admin_core import *  # noqa: F401,F403
from .admin_events import *  # noqa: F401,F403
from .admin_quests_rewards import *  # noqa: F401,F403
from .admin_activities_tasks import *  # noqa: F401,F403
from .admin_opportunities import *  # noqa: F401,F403
from .admin_moderation import *  # noqa: F401,F403
