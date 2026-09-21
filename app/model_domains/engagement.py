from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..time_utils import utc_storage_now
from .base import Base, UserRole, UserStatus

class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    xp_reward: Mapped[int] = mapped_column(Integer, default=20)
    starts_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    quest_type: Mapped[str] = mapped_column(String(24), default="individual")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    target_value: Mapped[int] = mapped_column(Integer, default=1)
    progress_value: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    postponed_reason: Mapped[str] = mapped_column(Text, default="")
    postponed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    participations: Mapped[list["QuestParticipation"]] = relationship(back_populates="quest")
    team: Mapped[Team | None] = relationship()

class QuestParticipation(Base):
    __tablename__ = "quest_participations"
    __table_args__ = (UniqueConstraint("quest_id", "user_id", name="uq_quest_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="joined")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    quest: Mapped[Quest] = relationship(back_populates="participations")
    user: Mapped[User] = relationship(back_populates="quest_participations")

class TeamQuestContribution(Base):
    __tablename__ = "team_quest_contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    value: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(255), default="")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(48), default="other")
    problem: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    expected_result: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    project_team: Mapped[str] = mapped_column(Text, default="")
    implementation_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    budget_resources: Mapped[str] = mapped_column(Text, default="")
    project_tasks: Mapped[str] = mapped_column(Text, default="")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    implementation_result: Mapped[str] = mapped_column(Text, default="")
    result_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    implementation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approval_xp_awarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class RequestCase(Base):
    __tablename__ = "request_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40), default="problem", index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(24), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(24), default="new", index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    response_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_response: Mapped[str] = mapped_column(Text, default="")
    internal_note: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    participant_last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class RequestMessage(Base):
    __tablename__ = "request_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("request_cases.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(24), default="participant", index=True)
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)

    case: Mapped[RequestCase] = relationship()
    sender: Mapped[User | None] = relationship()

class VolunteerTask(Base):
    __tablename__ = "volunteer_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=20)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    max_participants: Mapped[int] = mapped_column(Integer, default=1)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancellation_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    postponed_reason: Mapped[str] = mapped_column(Text, default="")
    postponed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Legacy single-assignee field is kept for backward compatibility only.
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    participations: Mapped[list["VolunteerTaskParticipation"]] = relationship(back_populates="task")

class VolunteerTaskParticipation(Base):
    __tablename__ = "volunteer_task_participations"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_volunteer_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("volunteer_tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="joined", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")

    task: Mapped[VolunteerTask] = relationship(back_populates="participations")
    user: Mapped[User] = relationship()

class ActivityType(Base):
    __tablename__ = "activity_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(64), default="other", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=10)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class QuickXPChallenge(Base):
    __tablename__ = "quick_xp_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(24), default="quiz", index=True)  # quiz|video|poll|comment
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=3)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=2)
    question: Mapped[str] = mapped_column(Text, default="")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    correct_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_url: Mapped[str] = mapped_column(String(500), default="")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    featured_home: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_by_label: Mapped[str] = mapped_column(String(160), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)


class QuickXPCompletion(Base):
    __tablename__ = "quick_xp_completions"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id", name="uq_quick_xp_challenge_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("quick_xp_challenges.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    answer_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)

    challenge: Mapped[QuickXPChallenge] = relationship()
    user: Mapped[User] = relationship()


class ActivityApplication(Base):
    __tablename__ = "activity_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_type_id: Mapped[int] = mapped_column(ForeignKey("activity_types.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="activity_requested", index=True)
    plan_text: Mapped[str] = mapped_column(Text, default="")
    result_note: Mapped[str] = mapped_column(Text, default="")
    result_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    hours_reward: Mapped[float] = mapped_column(Float, default=0)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    activity_type: Mapped[ActivityType] = relationship()
    user: Mapped[User] = relationship(foreign_keys=[user_id])

class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(80), default="можливість")
    direction: Mapped[str] = mapped_column(String(100), default="Інше")
    format: Mapped[str] = mapped_column(String(80), default="Онлайн/офлайн")
    age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    target_settlements: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

class OpportunityMatch(Base):
    __tablename__ = "opportunity_matches"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "user_id", name="uq_opportunity_match_user"),
        Index("ix_opportunity_matches_user_notified", "user_id", "notified_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    reasons_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="matched", index=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    opportunity: Mapped[Opportunity] = relationship()
    user: Mapped[User] = relationship()

class OpportunityInterest(Base):
    __tablename__ = "opportunity_interests"
    __table_args__ = (UniqueConstraint("opportunity_id", "user_id", name="uq_opportunity_interest_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="interested", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    opportunity: Mapped[Opportunity] = relationship()
    user: Mapped[User] = relationship()

class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    xp_reward: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)  # draft|published|closed
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    audience_type: Mapped[str] = mapped_column(String(24), default="all", index=True)  # all|users|event
    audience_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    created_by_label: Mapped[str] = mapped_column(String(160), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

class SurveyAudienceUser(Base):
    __tablename__ = "survey_audience_users"
    __table_args__ = (UniqueConstraint("survey_id", "user_id", name="uq_survey_audience_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    survey: Mapped[Survey] = relationship()
    user: Mapped[User] = relationship()

class SurveyQuestion(Base):
    __tablename__ = "survey_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(24), default="single")  # single|multiple|text
    options_text: Mapped[str] = mapped_column(Text, default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    survey: Mapped[Survey] = relationship()

class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (UniqueConstraint("survey_id", "user_id", name="uq_survey_response_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    answers_json: Mapped[str] = mapped_column(Text, default="{}")
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now)

    survey: Mapped[Survey] = relationship()
    user: Mapped[User] = relationship()

class ContentView(Base):
    """Aggregated Telegram detail views for participant-facing content.

    One row is kept per Telegram viewer and entity.  ``view_count`` stores
    repeated opens while the row itself provides the unique-viewer count.
    Admin/web page opens are intentionally not counted.
    """
    __tablename__ = "content_views"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "tg_id", name="uq_content_view_entity_tg"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    view_count: Mapped[int] = mapped_column(Integer, default=1)
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_storage_now, index=True)
