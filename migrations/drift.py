"""Detect models that have drifted away from the migrations.

Nothing forces a migration to be written for a model change, and the failure is
silent: the code works locally against a `create_all()` database and breaks in
whichever environment is actually migrated. A test turns that into a red build
on the commit that caused it.

The connection must point at a database migrated to head, not one built with
`metadata.create_all()` -- comparing the metadata against itself proves nothing.
"""

from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection

from .autogenerate import migration_options

__all__ = [
    "MigrationsPending",
    "pending_changes",
    "assert_no_migrations_pending",
    "assert_no_migrations_pending_async",
]


class MigrationsPending(AssertionError):
    """The models describe a schema the migrated database does not have.

    Subclasses AssertionError so pytest reports it as a plain failure.
    """

    def __init__(self, changes: list[Any]) -> None:
        self.changes: list[Any] = changes
        super().__init__(_message(changes))


def pending_changes(
    connection: Connection, target_metadata: MetaData, **options: Any
) -> list[Any]:
    """Alembic's raw diff between `connection`'s schema and the models.

    Empty when they agree. Runs under the same options as `run_migrations`, so a
    non-empty result means `alembic revision --autogenerate` would write a
    non-empty migration.
    """
    context = MigrationContext.configure(connection, opts=migration_options(**options))
    return compare_metadata(context, target_metadata)


def assert_no_migrations_pending(
    connection: Connection, target_metadata: MetaData, **options: Any
) -> None:
    """Raise `MigrationsPending` if a migration is owed."""
    changes = pending_changes(connection, target_metadata, **options)
    if changes:
        raise MigrationsPending(changes)


async def assert_no_migrations_pending_async(
    connection: AsyncConnection, target_metadata: MetaData, **options: Any
) -> None:
    """`assert_no_migrations_pending` over an async connection."""
    await connection.run_sync(assert_no_migrations_pending, target_metadata, **options)


def _message(changes: list[Any]) -> str:
    listed = "\n".join(f"  {_describe(change)}" for change in changes)
    return (
        f"{len(changes)} change(s) not in any migration. Run "
        f"`alembic revision --autogenerate` and commit the result:\n{listed}"
    )


def _describe(change: Any) -> str:
    """One alembic diff tuple, readable. The raw repr of a Table fills a screen."""
    if _is_grouped(change):
        return "; ".join(_describe(part) for part in change)
    kind, *subjects = change
    return f"{kind}: {'.'.join(_names_of(subjects))}"


def _is_grouped(change: Any) -> bool:
    """A modified column arrives as a list of the individual changes to it."""
    return isinstance(change, list)


def _names_of(subjects: list[Any]) -> list[str]:
    """Tables and Columns by name, dropping alembic's `existing_*` bookkeeping.

    Named before tested for emptiness: a Column compares as a SQL expression
    rather than as a boolean.
    """
    named = [
        str(getattr(item, "name", item)) for item in subjects if not _is_kwargs(item)
    ]
    return [name for name in named if name not in ("", "None")]


def _is_kwargs(subject: Any) -> bool:
    return isinstance(subject, dict)
