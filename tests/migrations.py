"""Tests for `release/migrations/`, against a real postgres.

The interesting cases are round trips -- render a migration, apply it, and check
autogenerate has nothing left to say. Asserting on the rendered string alone
would pass happily for source that does not import.
"""

import enum
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import Column, Engine, Integer, MetaData, inspect
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from release.columns import EnumField, PydanticJSONBField, PydanticJSONField
from release.migrations import (
    MigrationsPending,
    assert_no_migrations_pending,
    assert_no_migrations_pending_async,
    init,
    migration_options,
    pending_changes,
    render_item,
    upgrade,
)
from release.migrations.runtime import _database_url
from release.postgres.db import Database
from release.postgres.metadata import NAMING_CONVENTION

#: The scaffolded directory. Not "migrations", which is this module's own name.
SCRIPTS = "alembic_env"

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent


class Note(BaseModel):
    text: str


class Tier(enum.Enum):
    FREE = "free"
    PAID = "paid"


class MigrationBase(
    SQLModel, registry=registry(metadata=MetaData(naming_convention=NAMING_CONVENTION))
):
    """Own metadata, so these tables cannot collide with the rest of the suite."""


class Account(MigrationBase, table=True):
    __tablename__ = "migration_account"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    handle: str = Field(max_length=40, index=True)
    bio: str
    notes: list[Note] = PydanticJSONBField(Note, is_list=True, nullable=True)
    scratch: Note = PydanticJSONField(Note, nullable=True)
    tier: Tier = EnumField(Tier, default=Tier.FREE, name="migration_tier")


TARGET_METADATA = MigrationBase.metadata


def ours(obj: Any, name: str, type_: str, reflected: bool, compare_to: Any) -> bool:
    """An `include_object` filter -- the suite's other tables are not ours.

    Without it autogenerate would offer to drop every table `tests/columns.py`
    put in this database.
    """
    return type_ != "table" or name in TARGET_METADATA.tables


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, engine: Engine) -> Iterator[Path]:
    """A scaffolded project whose env.py points back at `TARGET_METADATA`."""
    drop_our_tables(engine)
    init(SCRIPTS, root=tmp_path, models="unused")
    _ = (tmp_path / SCRIPTS / "env.py").write_text(env_importing_this_module())
    yield tmp_path
    drop_our_tables(engine)


def drop_our_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        TARGET_METADATA.drop_all(connection)
        _ = connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        _ = connection.exec_driver_sql("DROP TYPE IF EXISTS migration_tier")


def env_importing_this_module() -> str:
    """An env.py reaching the models above, rather than the module `init` names.

    Run under `alembic` as a subprocess, `import migrations` finds this file, so
    both processes compare against the same metadata.
    """
    return textwrap.dedent(f"""
        import sys
        sys.path[:0] = [{str(_REPO_ROOT)!r}, {str(_TESTS_DIR)!r}]

        from release.migrations import run_migrations
        import migrations

        run_migrations(
            target_metadata=migrations.TARGET_METADATA,
            include_object=migrations.ours,
        )
        """)


def run_alembic(project: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def write_initial_migration(project: Path) -> None:
    run_alembic(project, "revision", "--autogenerate", "-m", "initial")


def apply_migrations(project: Path) -> None:
    run_alembic(project, "upgrade", "head")


def assert_settled(engine: Engine, metadata: MetaData) -> None:
    """`assert_no_migrations_pending`, scoped to the tables these tests own."""
    with engine.connect() as connection:
        assert_no_migrations_pending(connection, metadata, include_object=ours)


def only_revision(project: Path) -> Path:
    versions = sorted((project / SCRIPTS / "versions").glob("*.py"))
    assert len(versions) == 1, versions
    return versions[0]


# --------------------------------------------------------------------------
# the round trip
# --------------------------------------------------------------------------


def test_autogenerated_migration_applies_and_settles(
    project: Path, engine: Engine
) -> None:
    """Generate, apply, and find nothing left to generate.

    The second comparison is the real assertion: a type rendered as something
    postgres does not actually produce would show up here as a phantom change
    on every subsequent autogenerate.
    """
    write_initial_migration(project)
    apply_migrations(project)

    assert_settled(engine, TARGET_METADATA)


def test_generated_migration_needs_no_hand_editing(project: Path) -> None:
    """It imports cleanly, which alembic's own rendering does not manage.

    Left alone alembic emits `release.columns.PydanticJSONBType(...)`, with
    neither the import nor the required `model_class` argument.
    """
    write_initial_migration(project)
    revision = only_revision(project)
    source = revision.read_text()

    assert "release.columns" not in source
    assert "sqlmodel" not in source
    assert "postgresql.JSONB(astext_type=sa.Text())" in source
    assert "sa.JSON()" in source
    # the length is the difference between VARCHAR(40) and an unbounded column
    assert "sa.String(length=40)" in source

    _ = compile(source, str(revision), "exec")


def test_downgrade_returns_the_database_to_empty(project: Path, engine: Engine) -> None:
    """The generated `downgrade()` really does undo the `upgrade()`.

    A fresh `inspect()` each time -- an Inspector caches what it reflected, and
    the whole question here is what changed.
    """
    write_initial_migration(project)
    apply_migrations(project)
    assert inspect(engine).has_table("migration_account")

    run_alembic(project, "downgrade", "base")
    assert not inspect(engine).has_table("migration_account")


def test_offline_mode_emits_sql_without_connecting(project: Path) -> None:
    write_initial_migration(project)
    assert "CREATE TABLE migration_account" in run_alembic(
        project, "upgrade", "head", "--sql"
    )


async def test_upgrade_runs_in_process(project: Path, engine: Engine) -> None:
    """`upgrade` lends alembic a connection rather than building a second engine."""
    write_initial_migration(project)

    database = Database(pool="null")
    await upgrade(
        database.engine,
        script_location=str(project / SCRIPTS),
        ini_file=str(project / "alembic.ini"),
    )
    await database.disconnect()

    assert_settled(engine, TARGET_METADATA)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


class FakeAutogenContext:
    """The sliver of alembic's AutogenContext that `render_item` touches."""

    def __init__(self) -> None:
        self.imports: set[str] = set()


def test_third_party_types_are_left_alone_but_imported() -> None:
    """A type alembic names by module path gets exactly that module imported."""

    class Fake:
        pass

    Fake.__module__ = "some_vendor.types"
    context = FakeAutogenContext()

    assert render_item("type", Fake(), context) is False
    assert context.imports == {"import some_vendor.types"}


def test_alembics_own_types_need_no_help() -> None:
    context = FakeAutogenContext()

    assert render_item("type", Integer(), context) is False
    assert context.imports == set()


def test_autostring_length_is_not_dropped() -> None:
    from sqlmodel.sql.sqltypes import AutoString

    rendered = render_item("type", AutoString(length=40), FakeAutogenContext())
    assert rendered == "sa.String(length=40)"
    assert render_item("type", AutoString(), FakeAutogenContext()) == "sa.String()"


# --------------------------------------------------------------------------
# drift detection
# --------------------------------------------------------------------------


def models_with_an_extra_column() -> MetaData:
    """The models as a commit that changed one and forgot the migration."""
    moved = MetaData(naming_convention=NAMING_CONVENTION)
    for table in TARGET_METADATA.tables.values():
        _ = table.to_metadata(moved)
    moved.tables["migration_account"].append_column(Column("added_later", Integer))
    return moved


def test_drift_names_the_missing_change(project: Path, engine: Engine) -> None:
    write_initial_migration(project)
    apply_migrations(project)

    with pytest.raises(MigrationsPending) as raised:
        assert_settled(engine, models_with_an_extra_column())

    assert "migration_account.added_later" in str(raised.value)
    assert len(raised.value.changes) == 1


async def test_drift_check_works_over_an_async_connection(
    project: Path, async_session: AsyncSession
) -> None:
    """The shape a FastAPI project's test suite will actually use.

    Alembic is synchronous throughout, so this goes through `run_sync` -- worth
    covering separately, since the async stack is the one the library ships.
    """
    write_initial_migration(project)
    apply_migrations(project)

    await assert_no_migrations_pending_async(
        await async_session.connection(), TARGET_METADATA, include_object=ours
    )


def test_unmigrated_database_is_all_drift(project: Path, engine: Engine) -> None:
    with engine.connect() as connection:
        assert pending_changes(connection, TARGET_METADATA, include_object=ours)


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


def test_url_survives_a_percent_in_the_password() -> None:
    """Why the url is never written back through `set_main_option`.

    ConfigParser interpolates on the way in, so a `%` in a password blows up at
    migration time -- far from where the credential was set.
    """
    url = _database_url(Config(), "postgresql+asyncpg://u:p%ss:w%rd@h:5432/n")
    assert url == "postgresql+asyncpg://u:p%ss:w%rd@h:5432/n"

    with pytest.raises(ValueError):
        Config().set_main_option("sqlalchemy.url", url)


def test_placeholder_url_in_the_ini_is_ignored(tmp_path: Path) -> None:
    """`alembic init`'s stub must not be mistaken for a configured database."""
    ini = tmp_path / "alembic.ini"
    _ = ini.write_text(
        "[alembic]\nsqlalchemy.url = driver://user:pass@localhost/dbname\n"
    )

    fell_through_to_the_environment = _database_url(Config(str(ini)), None)
    assert fell_through_to_the_environment.startswith("postgresql+asyncpg://")


def test_comparison_options_are_on_by_default() -> None:
    """Alembic defaults both to False, which silently ignores type changes."""
    options = migration_options()

    assert options["compare_type"] is True
    assert options["compare_server_default"] is True
    assert options["render_item"] is render_item


def test_overrides_win_over_the_defaults() -> None:
    options = migration_options(compare_server_default=False, version_table="other")

    assert options["compare_server_default"] is False
    assert options["version_table"] == "other"


# --------------------------------------------------------------------------
# scaffolding
# --------------------------------------------------------------------------


def test_init_writes_a_working_layout(tmp_path: Path) -> None:
    init(SCRIPTS, root=tmp_path, models="myapp.models")

    assert (tmp_path / "alembic.ini").exists()
    assert (tmp_path / SCRIPTS / "versions").is_dir()

    env = (tmp_path / SCRIPTS / "env.py").read_text()
    assert "import myapp.models" in env
    # the templates address the library by whatever directory it was vendored
    # into, which is `release` in this repo
    assert "from release.migrations import run_migrations" in env
    _ = compile(env, "env.py", "exec")

    assert f"script_location = {SCRIPTS}" in (tmp_path / "alembic.ini").read_text()


def test_init_does_not_clobber(tmp_path: Path) -> None:
    init(SCRIPTS, root=tmp_path)
    _ = (tmp_path / SCRIPTS / "env.py").write_text("# mine\n")

    init(SCRIPTS, root=tmp_path)
    assert (tmp_path / SCRIPTS / "env.py").read_text() == "# mine\n"

    init(SCRIPTS, root=tmp_path, force=True)
    assert "run_migrations" in (tmp_path / SCRIPTS / "env.py").read_text()


def test_init_appends_to_an_existing_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _ = pyproject.write_text('[project]\nname = "demo"\n')

    init(SCRIPTS, root=tmp_path, config="pyproject")

    content = pyproject.read_text()
    assert content.startswith('[project]\nname = "demo"\n')
    assert f'script_location = "{SCRIPTS}"' in content
    # the ini is left holding logging only
    assert "script_location" not in (tmp_path / "alembic.ini").read_text()

    init(SCRIPTS, root=tmp_path, config="pyproject")
    assert pyproject.read_text().count("[tool.alembic]") == 1


def test_init_rejects_an_unknown_config_style(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        init(SCRIPTS, root=tmp_path, config="yaml")
