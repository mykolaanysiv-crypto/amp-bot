from sqlalchemy import inspect


async def test_database_init_is_idempotent_and_has_reliability_tables(db):
    await db.init()
    await db.init()
    async with db.engine.begin() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    assert "scheduled_jobs" in tables
    assert "notification_deliveries" in tables
    assert "broadcast_recipients" in tables
