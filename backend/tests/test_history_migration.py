from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import Base, _add_missing_columns


async def test_existing_sqlite_history_is_preserved_and_migration_is_repeatable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text('''CREATE TABLE messages (
                id INTEGER PRIMARY KEY, company_id INTEGER, role VARCHAR(20),
                content TEXT, created_at DATETIME)'''))
            await conn.execute(text("INSERT INTO messages VALUES (1, 1, 'user', 'legacy history', '2026-11-01 00:00:00')"))
            await conn.execute(text('''CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, company_id INTEGER, prompt TEXT, interval_minutes INTEGER,
                active BOOLEAN, last_run DATETIME)'''))
            await conn.execute(text("INSERT INTO tasks VALUES (1, 1, 'legacy task', 1440, 1, NULL)"))
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)
            await conn.run_sync(_add_missing_columns)
            row = (await conn.execute(text('SELECT content, user_id, run_id FROM messages'))).one()
            assert tuple(row) == ('legacy history', None, None)
            assert (await conn.execute(text('SELECT prompt, created_by FROM tasks'))).one() == ('legacy task', None)
            indexes = await conn.run_sync(lambda c: inspect(c).get_indexes('messages'))
            assert any(index['column_names'] == ['user_id'] for index in indexes)
    finally:
        await engine.dispose()
