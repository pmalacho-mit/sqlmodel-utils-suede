from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, Inspector, inspect, text
from sqlmodel import Session, SQLModel, create_engine

# Imported for the side effect: it swaps SQLModel.metadata for one carrying the
# library's naming convention, so constraint/index names here match production.
# Must land before any table model is defined.
import release.metadata  # noqa: F401
from release.postgres.config import ConfigFromEnvironment, config_to_url


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
