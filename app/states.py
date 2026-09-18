from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    privacy_notice = State()
    last_name = State()
    first_name = State()
    phone = State()
    email = State()
    settlement = State()
    birth_date = State()
    gender = State()
    vulnerabilities = State()
    vulnerability_other = State()
    media_consent = State()


class IdeaState(StatesGroup):
    title = State()
    category = State()
    problem = State()
    description = State()
    audience = State()
    expected_result = State()
    resources = State()


class RequestState(StatesGroup):
    category = State()
    title = State()
    description = State()
    has_photo = State()
    photo = State()
    reply = State()


class QRBadgeState(StatesGroup):
    photo = State()


class ActivityApplicationState(StatesGroup):
    plan_text = State()
    result_note = State()
    result_photo = State()


class AdminXPState(StatesGroup):
    user_id = State()
    amount = State()
    description = State()


class AdminEventScannerState(StatesGroup):
    scanning = State()


class AdminEventState(StatesGroup):
    title = State()
    description = State()
    day = State()
    month = State()
    year = State()
    event_time = State()
    location = State()
    xp_reward = State()
    volunteer_hours = State()


class AdminQuestState(StatesGroup):
    title = State()
    description = State()
    xp_reward = State()
    deadline_day = State()
    deadline_month = State()
    deadline_year = State()
    deadline_time = State()


class AdminRewardState(StatesGroup):
    title = State()
    description = State()
    min_xp = State()
    stock = State()


class AdminTaskState(StatesGroup):
    title = State()
    description = State()
    xp_reward = State()
    hours_reward = State()
    deadline_day = State()
    deadline_month = State()
    deadline_year = State()
    deadline_time = State()


class AdminOpportunityState(StatesGroup):
    title = State()
    kind = State()
    description = State()
    deadline = State()
    url = State()


class AdminBroadcastState(StatesGroup):
    text = State()


class AdminBadgeAwardState(StatesGroup):
    user_id = State()
    badge_id = State()


class AdminBanState(StatesGroup):
    user_id = State()
    days = State()
    reason = State()
    shorten_days = State()


class SurveyState(StatesGroup):
    text_answer = State()


class StreakFreezeState(StatesGroup):
    days = State()


class RestorationState(StatesGroup):
    reason = State()
    future_activity = State()
    confirmation = State()


class EventFeedbackState(StatesGroup):
    comment = State()


class AmbassadorReportState(StatesGroup):
    period_start = State()
    period_end = State()
    description = State()
    photo = State()
