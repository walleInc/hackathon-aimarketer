from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Наивное UTC-время: одинаково работает в SQLite и PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _add_missing_columns(conn) -> None:
    """Мини-миграция: добавляет новые колонки в уже существующие таблицы (пока нет Alembic)."""
    insp = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            default = ""
            if col.default is not None and col.default.is_scalar:
                v = col.default.arg
                default = (" DEFAULT TRUE" if v else " DEFAULT FALSE") if isinstance(v, bool) else (f" DEFAULT '{v}'" if isinstance(v, str) else f" DEFAULT {int(v)}")
            conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(conn.dialect)}{default}'))
    # create_all skips existing tables, including indexes on newly added columns.
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            index.create(conn, checkfirst=True)


async def init_db() -> None:
    from . import models  # noqa: F401  (регистрация таблиц)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
