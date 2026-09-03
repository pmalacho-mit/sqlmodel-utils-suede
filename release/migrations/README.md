# Alembic migrations

Wiring so that alembic works with this library's models and column types. Three
pieces, usable independently.

Requires `alembic` (in `requirements.txt`); nothing else in the library imports
it. Replace `release` below with whatever directory you vendored this into.

## Setting up

```bash
python -m release.migrations init migrations --models myapp.models.all
```

Writes `migrations/{env.py,script.py.mako,versions/,README}` and an
`alembic.ini`. Add `--config pyproject` to put alembic's settings in
`pyproject.toml` under `[tool.alembic]` instead (needs alembic >= 1.16), leaving
`alembic.ini` holding only the logging config. Then:

```bash
alembic revision --autogenerate -m "add widgets"
alembic upgrade head
```

The database url is **not** written to `alembic.ini`. `env.py` resolves it from
the same `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` the application reads,
so there is one source of truth and no credentials in the repo.

## Why not alembic's own template

`alembic init -t async` writes ~90 lines that every project then edits the same
way. `run_migrations` is that file with the project-specific parts as keyword
arguments:

```python
from release.migrations import run_migrations
from release.postgres.metadata import Base
import myapp.models.all  # noqa: F401

run_migrations(target_metadata=Base.metadata)
```

It differs from the stock template in four ways that matter:

**Custom types render as something importable.** Alembic renders a
`TypeDecorator` as `<module>.<Class>(<recovered args>)` and never imports the
module, so a `PydanticJSONBField` column comes out as

```python
sa.Column('notes', release.columns.PydanticJSONBType(none_as_null=True, astext_type=Text()), ...)
```

— an undefined name, a bare `Text()`, and no `model_class`, which is a required
argument. That file raises on import. `render_item` renders these as the
`postgresql.JSONB()` / `sa.JSON()` the database actually sees (the pydantic
layer is python-side only, with no schema footprint) and adds an import for any
other third-party type it renders, so pgvector and friends work untouched.
`AutoString` renders as `sa.String(length=...)`, keeping migrations free of
sqlmodel internals.

**`compare_type` and `compare_server_default` are on.** Alembic defaults both to
`False`, so a stock setup silently ignores every column type change.

**A `%` in the password doesn't break migrations.** The usual
`config.set_main_option("sqlalchemy.url", ...)` round-trips the value through
ConfigParser interpolation, which raises on `%`. The url is passed to the engine
directly instead.

Async only, like the rest of the library — `env.py` is yours to edit if you need
otherwise. Offline mode (`alembic upgrade head --sql`) needs no driver and works
either way.

## Catching a missing migration

Nothing forces a migration to be written for a model change, and the failure is
silent — the code works locally against `create_all()` and breaks wherever the
schema is actually migrated. In a test, against a database migrated to head:

```python
from release.migrations import assert_no_migrations_pending_async

async def test_models_match_migrations(async_session):
    await assert_no_migrations_pending_async(
        await async_session.connection(), Base.metadata
    )
```

Comparison runs under the same options as autogenerate, so a failure here means
`alembic revision --autogenerate` would write a non-empty migration. If the
database holds tables this project does not own, pass alembic's own
`include_object` filter -- here and to `run_migrations`, or autogenerate will
offer to drop them:

```python
def mine(obj, name, type_, reflected, compare_to):
    return type_ != "table" or name in Base.metadata.tables
```

## Migrating on startup

```python
from release.migrations import upgrade

database = Database()
await upgrade(database.engine, script_location="migrations")
```

Hands alembic the connection rather than building a second engine from a second
copy of the configuration, and fails the process loudly if the migration fails.

Only safe for a single migrating process — alembic takes no lock of its own, so
two instances booting together can race. Run it as a job or an init container if
that matters.
