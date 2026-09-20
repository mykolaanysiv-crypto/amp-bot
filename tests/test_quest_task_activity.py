from app.model_domains import ActivityApplication, ActivityType, Quest, QuestParticipation, VolunteerTask, VolunteerTaskParticipation
from app.domain_services import complete_activity_application, xp_total
from app.workflows import approve_quest_participation, approve_volunteer_task_participation
from tests.conftest import create_user


async def test_quest_join_submit_approve_xp_once(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=12001)
        quest = Quest(title="Квест", description="", xp_reward=25, status="open")
        session.add(quest); await session.flush()
        part = QuestParticipation(quest_id=quest.id, user_id=user.id, status="completed")
        session.add(part); await session.flush()
        first = await approve_quest_participation(session, quest, part, user)
        second = await approve_quest_participation(session, quest, part, user)
        assert first is not None
        assert second is None
        assert part.status == "approved"
        assert await xp_total(session, user.id) == quest.xp_reward


async def test_volunteer_submit_approve_adds_xp_and_hours_once(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=12002)
        task = VolunteerTask(title="Толока", xp_reward=20, hours_reward=2.0, status="open")
        session.add(task); await session.flush()
        part = VolunteerTaskParticipation(task_id=task.id, user_id=user.id, status="submitted")
        session.add(part); await session.flush()
        first = await approve_volunteer_task_participation(session, task, part, user)
        second = await approve_volunteer_task_participation(session, task, part, user)
        assert first is not None
        assert second is None
        assert await xp_total(session, user.id) == task.xp_reward
        assert user.volunteer_hours == 2.0


async def test_activity_evidence_complete_is_idempotent(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=12003)
        activity = ActivityType(code="test_activity", title="Активність", xp_reward=15, hours_reward=1.0, active=True)
        session.add(activity); await session.flush()
        application = ActivityApplication(
            activity_type_id=activity.id, user_id=user.id, status="activity_submitted",
            result_note="Виконано", result_image_path="media:1", xp_reward=15, hours_reward=1.0,
        )
        session.add(application); await session.flush()
        first = await complete_activity_application(session, application)
        second = await complete_activity_application(session, application)
        assert first is not None
        assert second is None
        assert application.status == "activity_completed"
        assert await xp_total(session, user.id) == 15
        assert user.volunteer_hours == 1.0
