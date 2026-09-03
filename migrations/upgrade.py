"""Run migrations in-process, over an engine the application already owns.

For containers that migrate on boot. Shelling out to `alembic upgrade head`
would build a second engine from a second copy of the configuration; lending
alembic the connection keeps one url in play, and the process fails to start --
loudly -- if the migration fails.

Only safe for a single migrating process. Two instances booting at once will
race: alembic takes no lock of its own, and while postgres serialises the DDL,
the loser can still fail on a duplicate object. Run it as a job, an init
container, or behind a lock if that matters.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from .runtime import lend_connection

__all__ = ["upgrade"]


async def upgrade(
    engine: AsyncEngine,
    *,
    script_location: str | Path,
    revision: str = "head",
    ini_file: str | Path | None = None,
) -> None:
    """Upgrade to `revision` over an existing async engine.

    Alembic is synchronous throughout, so the migrations run in the thread
    `run_sync` provides rather than on the event loop.

    Args:
        engine: the application's engine, whose connection alembic borrows.
        script_location: the migrations directory -- the one holding `env.py`.
        revision: what to upgrade to.
        ini_file: an alembic.ini to load first, for its logging config.
    """
    config = _config(script_location, ini_file)
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade, config, revision)


def _config(script_location: str | Path, ini_file: str | Path | None) -> Config:
    config = Config(str(ini_file) if ini_file is not None else None)
    config.set_main_option("script_location", str(script_location))
    return config


def _upgrade(connection: Connection, config: Config, revision: str) -> None:
    lend_connection(config, connection)
    command.upgrade(config, revision)
