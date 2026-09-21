"""Compatibility facade for participant handlers.

Canonical route handlers are split across focused modules.  This facade keeps
public imports stable for the v1.13.x compatibility window without wildcard
imports.
"""
from .participant_common import router
from .participant_home import (
    overview, join_hub, more_hub, streaks_menu, profile, xp_history, badges, rewards,
)
from .participant_requests import idea_start, request_menu
from .participant_opportunities import opportunities, participant_goals
from .participant_activities import activity_catalog
from .participant_tasks import tasks, leaderboard, rules
from .quick_xp import quick_xp_hub
# Import all modules above registers their decorators on the shared router.

__all__ = [
    "router", "overview", "join_hub", "more_hub", "streaks_menu", "profile",
    "xp_history", "badges", "rewards", "idea_start", "request_menu",
    "opportunities", "participant_goals", "activity_catalog", "tasks",
    "leaderboard", "rules", "quick_xp_hub",
]
