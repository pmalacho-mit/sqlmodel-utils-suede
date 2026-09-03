"""The body of a consumer's `env.py`, which `scaffold` writes from a template.

Alembic's async template is ~90 lines that every project copies and then edits
the same way. What is left after taking out the parts that are not a project
decision is one call.

Async only, like the rest of the library. Offline mode needs no driver at all
and works either way.
"""

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import MetaData, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from ..postgres.config import ConfigFromEnvironment, config_to_url
from .autogenerate import migration_options

__all__ = ["run_migrations", "lend_connection"]

_LENT_CONNECTION = "connection"
_PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"


def run_migrations(
    *, target_metadata: MetaData | None, url: str | None = None, **options: Any
) -> None:
    """Run whichever migrations alembic invoked this `env.py` for.

    Args:
        target_metadata: what autogenerate compares against, normally
            `Base.metadata`. Every module defining a table must already be
            imported, or autogenerate reads the missing tables as deletions.
        url: the database to migrate. Defaults to the ini file's
            `sqlalchemy.url` if it has been set to something real, and otherwise
            to the same environment variables the application reads.
        **options: passed to `migration_options`, and win over its defaults.
    """
    from alembic import context

    config = context.config
    _apply_logging_config(config)
    settings = migration_options(target_metadata=target_metadata, **options)

    lent = _lent_connection(config)
    if lent is not None:
        _migrate(lent, settings)
    elif context.is_offline_mode():
        _emit_sql(_database_url(config, url), settings)
    else:
        asyncio.run(_connect_and_migrate(config, _database_url(config, url), settings))


def lend_connection(config: Any, connection: Connection) -> None:
    """Offer `run_migrations` a connection instead of letting it open its own."""
    config.attributes[_LENT_CONNECTION] = connection


def _lent_connection(config: Any) -> Connection | None:
    return config.attributes.get(_LENT_CONNECTION)


def _apply_logging_config(config: Any) -> None:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)


def _database_url(config: Any, override: str | None) -> str:
    return override or _url_from_ini(config) or config_to_url(ConfigFromEnvironment())


def _url_from_ini(config: Any) -> str | None:
    """The ini's url, unless it is absent or still the stub `alembic init` writes."""
    url = config.get_main_option("sqlalchemy.url", None)
    return url if url and url != _PLACEHOLDER_URL else None


def _migrate(connection: Connection, settings: dict[str, Any]) -> None:
    _configure_and_run(connection=connection, **settings)


def _emit_sql(url: str, settings: dict[str, Any]) -> None:
    """Write the migrations to stdout as SQL, without connecting to anything."""
    _configure_and_run(
        url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **settings
    )


def _configure_and_run(**settings: Any) -> None:
    from alembic import context

    context.configure(**settings)
    with context.begin_transaction():
        context.run_migrations()


async def _connect_and_migrate(config: Any, url: str, settings: dict[str, Any]) -> None:
    engine = async_engine_from_config(
        _engine_settings(config, url), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_migrate, settings)
    finally:
        await engine.dispose()


def _engine_settings(config: Any, url: str) -> dict[str, Any]:
    """The ini's `sqlalchemy.*` settings, with the url written into the result.

    Into the result rather than back into the config, because
    `config.set_main_option("sqlalchemy.url", ...)` round-trips the value
    through ConfigParser interpolation, which raises on a `%` in the password.
    """
    settings = dict(config.get_section(config.config_ini_section, {}) or {})
    settings["sqlalchemy.url"] = url
    return settings
