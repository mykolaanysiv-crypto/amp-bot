from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.models import Notification, ScheduledJob
from app.reliability import acquire_job_lock, finish_job_lock, process_due_telegram_deliveries, queue_telegram_delivery


class FlakyBot:
    def __init__(self):
        self.calls = 0
    async def send_message(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary telegram error")
        return True


async def test_scheduler_lock_excludes_second_worker_and_recovers_after_release(db):
    owner1 = await acquire_job_lock(db, "test_job", ttl_seconds=60, owner="worker-1")
    owner2 = await acquire_job_lock(db, "test_job", ttl_seconds=60, owner="worker-2")
    assert owner1 == "worker-1"
    assert owner2 is None
    await finish_job_lock(db, "test_job", owner1, success=True)
    owner2 = await acquire_job_lock(db, "test_job", ttl_seconds=60, owner="worker-2")
    assert owner2 == "worker-2"
    await finish_job_lock(db, "test_job", owner2, success=True)


async def test_notification_retry_then_success(db):
    async with db.session_factory() as session:
        await queue_telegram_delivery(session, 15001, "Тест", source="test", dedupe_key="test:retry")
        await session.commit()
    bot = FlakyBot()
    first = await process_due_telegram_deliveries(bot, db)
    assert first["retry"] == 1
    async with db.session_factory() as session:
        row = await session.scalar(select(Notification).where(Notification.dedupe_key == "test:retry"))
        row.scheduled_at = datetime.utcnow() - timedelta(seconds=1)
        await session.commit()
    second = await process_due_telegram_deliveries(bot, db)
    assert second["sent"] == 1
    async with db.session_factory() as session:
        row = await session.scalar(select(Notification).where(Notification.dedupe_key == "test:retry"))
        assert row.status == "sent"
        assert row.retry_count == 1


class AlwaysFailBot:
    def __init__(self):
        self.calls = 0
    async def send_message(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("telegram unavailable")


async def test_notification_retries_three_times_then_fails(db):
    async with db.session_factory() as session:
        row = await queue_telegram_delivery(session, 15002, "Fail", source="test", dedupe_key="test:fail")
        await session.commit()
        assert row.max_attempts == 4

    bot = AlwaysFailBot()
    expected_statuses = ["retry", "retry", "retry", "failed"]
    for expected in expected_statuses:
        result = await process_due_telegram_deliveries(bot, db)
        async with db.session_factory() as session:
            row = await session.scalar(select(Notification).where(Notification.dedupe_key == "test:fail"))
            assert row.status == expected
            if expected == "retry":
                assert result["retry"] == 1
                row.scheduled_at = datetime.utcnow() - timedelta(seconds=1)
                await session.commit()
            else:
                assert result["failed"] == 1
                assert row.status == "failed"
                assert row.retry_count == 4

    assert bot.calls == 4
