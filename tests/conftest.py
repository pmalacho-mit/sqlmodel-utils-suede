from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import Engine, Inspector, inspect, text
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.ext.asyncio.session import AsyncSession

# Swaps SQLModel.metadata for one carrying the library's naming convention, so
# constraint/index names here match production. Must run before any table model
# is defined -- hence at import time, not in a fixture.
from release.postgres.metadata import install_global_naming_conventions
from release.postgres.config import ConfigFromEnvironment, config_to_url
from release.postgres.db import Database

_ = install_global_naming_conventions()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(config_to_url(ConfigFromEnvironment(), addon="psycopg"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def schema(engine: Engine) -> Iterator[None]:
    # a `--keep`ed stack can carry tables (and enum types) over from a prior run
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> None:
    """Empty every table before each test, so ordering can't couple them."""
    tables = ", ".join(f'"{table.name}"' for table in SQLModel.metadata.sorted_tables)
    if not tables:
        return
    with engine.begin() as connection:
        _ = connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def inspector(engine: Engine) -> Inspector:
    return inspect(engine)


@pytest.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    """
    A session over the stack the library actually ships: `Database` ->
    create_async_engine -> asyncpg. Worth its own fixture because asyncpg's
    handling of json/jsonb/enum is nothing like psycopg's.
    """
    database = Database(pool="null")
    async with database.session() as session:
        yield session
    await database.disconnect()
