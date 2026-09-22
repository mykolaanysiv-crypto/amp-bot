from __future__ import annotations

from ..registration_ux import mark_first_activity

import asyncio
import hashlib

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..gamification import CLAIMABLE_ACTIVITY_CATALOG, get_level, referral_reward_for_position, normalize_event_xp, normalize_quest_xp
from ..profile_data import gender_label, media_consent_label, vulnerability_labels, participant_first_name, split_display_name
from ..ui_labels import label, event_registration_status_label
from ..security import hash_password
from ..runtime_config import ensure_runtime_defaults, get_runtime_int
from ..time_utils import event_local_now
from ..model_domains import (
    ActivityApplication,
    ActivityType,
    AuditLog,
    BanRecord,
    Badge,
    Event,
    EventRegistration,
    Idea,
    Opportunity,
    RequestCase,
    Quest,
    QuestParticipation,
    Referral,
    Reward,
    RewardClaim,
    Season,
    SurveyResponse,
    ParticipationStreak,
    Team,
    TeamMember,
    User,
    UserBadge,
    UserRole,
    UserStatus,
    VolunteerTask,
    VolunteerTaskParticipation,
    XPTransaction,
    WebStaffAccount,
)



__all__ = [name for name in globals() if not name.startswith("__")]
