from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, or_, select

from ..db import Database
from ..gamification import LEVELS, get_level, progress_text
from ..keyboards import (compact_button_text, entity_button_text, events_keyboard, rewards_keyboard, tasks_keyboard,
                         main_menu, join_hub_keyboard, profile_hub_keyboard, more_hub_keyboard)
from ..media import telegram_photo_input, save_telegram_photo
from ..models import (
    ActivityApplication,
    ActivityType,
    Badge,
    Event,
    EventFeedback,
    EventRegistration,
    Idea,
    Opportunity,
    OpportunityInterest,
    OpportunityMatch,
    Quest,
    QuestParticipation,
    RequestCase,
    RequestMessage,
    Reward,
    RewardClaim,
    User,
    UserBadge,
    UserStatus,
    VolunteerTask, VolunteerTaskParticipation,
    XPTransaction,
)
from ..profile_data import participant_first_name
from ..services import current_season, get_user_by_tg, log_audit, season_xp, xp_total
from ..engagement import active_month_streak, goals_for_user, process_expired_content
from ..leagues import (
    MAX_FREEZE_DAYS_PER_QUARTER, create_streak_freeze, league_for_xp, league_leaderboard_rows,
    refresh_user_streak, restore_super_streak, season_leaderboard_rows, streak_freeze_summary,
)
from ..ui_labels import activity_category_label, activity_status_label, idea_status_label, label, request_status_label
from ..states import ActivityApplicationState, IdeaState, RequestState, StreakFreezeState
from ..opportunity_matching import OPPORTUNITY_INTERESTS, refresh_matches_for_user, set_user_interests, user_interests
from ..runtime_config import get_runtime_int
from ..registration_ux import get_registration_journey
from ..content_views import content_view_stat, record_content_view
from ..time_utils import event_local_now

router = Router(name="participant")


async def _active_user(message_or_cb, db: Database):
    tg_id = message_or_cb.from_user.id
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, tg_id)
        return user





# Export compatibility helpers, including private names, to split modules.
__all__ = [name for name in globals() if not name.startswith("__")]
