"""Alembic support for projects built on this library.

Three pieces, usable independently:

* `run_migrations` -- the whole of a consumer's env.py. Handles the async engine,
  the database url, and the autogenerate options and render hook without which
  this library's column types produce migration files that will not import.
* `assert_no_migrations_pending` -- a test that fails when the models have moved
  and nobody wrote the migration.
* `upgrade` -- `alembic upgrade head` in-process at startup, over an engine the
  application already has.

Start with `python -m <this package>.migrations init`. See README.md.

Alembic is not a dependency of the rest of the library; importing this package
requires it.
"""

from .autogenerate import migration_options, render_item
from .drift import (
    MigrationsPending,
    assert_no_migrations_pending,
    assert_no_migrations_pending_async,
    pending_changes,
)
from .runtime import run_migrations
from .scaffold import init
from .upgrade import upgrade

__all__ = [
    "run_migrations",
    "migration_options",
    "render_item",
    "MigrationsPending",
    "pending_changes",
    "assert_no_migrations_pending",
    "assert_no_migrations_pending_async",
    "upgrade",
    "init",
]
