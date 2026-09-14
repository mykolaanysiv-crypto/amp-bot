from datetime import datetime

from app.models import Idea, RequestCase, RequestMessage, Survey
from app.services import xp_total
from app.workflows import award_idea_approval_once, complete_survey_once
from tests.conftest import create_user


async def test_survey_response_unique_and_xp_once(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=13001)
        survey = Survey(title="Опитування", xp_reward=5, status="published")
        session.add(survey); await session.flush()
        first, reward, state = await complete_survey_once(session, survey, user, {"1": "Так"})
        second, second_reward, second_state = await complete_survey_once(session, survey, user, {"1": "Ні"})
        assert first is not None
        assert reward == 5 and state == "completed"
        assert second is first
        assert second_reward == 0 and second_state == "already_completed"
        assert await xp_total(session, user.id) == 5


async def test_idea_approval_bonus_and_mini_project_fields(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=13002)
        idea = Idea(user_id=user.id, title="Нова лавка", description="", status="approved")
        session.add(idea); await session.flush()
        first_tg, first_text = await award_idea_approval_once(session, idea)
        second_tg, second_text = await award_idea_approval_once(session, idea)
        idea.project_team = "АМПасадори"
        idea.project_tasks = "Підготувати; реалізувати"
        idea.progress_percent = 25
        assert first_tg == user.tg_id and "+10 XP" in first_text
        assert second_tg is None and second_text == ""
        assert await xp_total(session, user.id) == 10
        assert idea.approval_xp_awarded_at is not None
        assert idea.progress_percent == 25


async def test_case_assignment_reply_close(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=13003)
        staff = await create_user(session, tg_id=13004, name="Координатор")
        case = RequestCase(user_id=user.id, title="Питання", description="Тест", status="new", assigned_user_id=staff.id)
        session.add(case); await session.flush()
        case.status = "in_progress"
        session.add(RequestMessage(case_id=case.id, sender_type="staff", sender_user_id=staff.id, body="Відповідь"))
        case.status = "closed"; case.resolved_at = datetime.utcnow(); case.updated_at = datetime.utcnow()
        await session.commit()
        assert case.assigned_user_id == staff.id
        assert case.status == "closed"
        assert case.resolved_at is not None
