from __future__ import annotations

from aiogram import Bot
from ..db import Database
from .birthdays import _birthday_scheduler
from .events import _event_reminder_scheduler, _event_feedback_scheduler
from .engagement import (
    _streak_scheduler, _goal_reward_scheduler, _inactivity_scheduler,
    _smart_opportunities_scheduler, _season_history_scheduler, _content_lifecycle_scheduler,
)
from .delivery import _notification_retry_scheduler, _notification_health_scheduler, _backup_health_scheduler
from .donations import _donation_sync_scheduler


def scheduler_factories(bot: Bot, db: Database, settings):
    return {
        "birthday_scheduler": lambda: _birthday_scheduler(bot, db, settings),
        "event_reminder_scheduler": lambda: _event_reminder_scheduler(bot, db, settings),
        "event_feedback_scheduler": lambda: _event_feedback_scheduler(bot, db),
        "goal_reward_scheduler": lambda: _goal_reward_scheduler(bot, db),
        "streak_scheduler": lambda: _streak_scheduler(bot, db),
        "notification_retry_scheduler": lambda: _notification_retry_scheduler(bot, db),
        "participant_inactivity_scheduler": lambda: _inactivity_scheduler(bot, db),
        "smart_opportunities_scheduler": lambda: _smart_opportunities_scheduler(bot, db),
        "season_history_scheduler": lambda: _season_history_scheduler(bot, db),
        "donation_sync_scheduler": lambda: _donation_sync_scheduler(bot, db, settings),
        "notification_health_scheduler": lambda: _notification_health_scheduler(bot, db, settings),
        "backup_health_scheduler": lambda: _backup_health_scheduler(bot, db, settings),
        "content_lifecycle_scheduler": lambda: _content_lifecycle_scheduler(db),
    }
