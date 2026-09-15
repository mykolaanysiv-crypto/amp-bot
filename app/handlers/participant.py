"""Compatibility facade for split participant handlers (v1.12)."""
from .participant_common import router
from .participant_home import *  # noqa: F401,F403
from .participant_requests import *  # noqa: F401,F403
from .participant_opportunities import *  # noqa: F401,F403
from .participant_activities import *  # noqa: F401,F403
from .participant_tasks import *  # noqa: F401,F403
