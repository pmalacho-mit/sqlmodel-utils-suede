from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Literal, TypedDict, Unpack

from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker
from sqlmodel import SQLModel, Session, text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.pool import NullPool

from .config import Config, ConfigFromEnvironment, config_to_url, PostgresAddOn
from ..metadata import *


def extension_command(extension: str):
    return text(f"CREATE EXTENSION IF NOT EXISTS {extension}")


class PoolConfig(TypedDict):
    size: int
    overflow: int


class ConstructorArgs(TypedDict, total=False):
    config: Config
    echo: bool
    addon: PostgresAddOn
    expire_on_commit: bool
    pool: PoolConfig | Literal["null"]
    extensions: list[str] | None


class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    sessionmaker_no_expire: async_sessionmaker[AsyncSession]

    __extensions: list[str] | None
    __extensions_added = False

    @property
    def sync_engine(self):
        return self.engine.sync_engine

    def __init__(self, **kwargs: Unpack[ConstructorArgs]):
        config = kwargs.get("config", ConfigFromEnvironment())
        addon = kwargs.get("addon", "asyncpg")
        echo = kwargs.get("echo", False)
        expire_on_commit = kwargs.get("expire_on_commit", False)
        pool = kwargs.get("pool", {"size": 10, "overflow": 40})
        self.__extensions = kwargs.get("extensions")

        url = config_to_url(config, addon=addon)
        self.engine = (
            create_async_engine(url, echo=echo, poolclass=NullPool)
            if pool == "null"
            else create_async_engine(
                url,
                echo=echo,
                pool_size=pool["size"],
                max_overflow=pool["overflow"],
            )
        )

        self.sessionmaker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=expire_on_commit,
            close_resets_only=False,
        )

        self.sessionmaker_no_expire = (
            self.sessionmaker
            if not expire_on_commit
            else async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                close_resets_only=False,
            )
        )

    async def disconnect(self):
        await self.engine.dispose()

    def sync_session(self) -> Session:
        return Session(self.engine.sync_engine)

    @asynccontextmanager
    async def session(
        self, *, force_no_expire_on_commit=False   # pyright: ignore[reportMissingParameterType]
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        Returns an async session. If autoconnect is True, the database will be connected if it is not already connected (using a configuration retrieved from environment variables).
        """
        sessionmaker = (
            self.sessionmaker_no_expire
            if force_no_expire_on_commit
            else self.sessionmaker
        )
        async with sessionmaker() as session:
            try:
                if self.__extensions != None and not self.__extensions_added:
                    for extension in self.__extensions:
                        _ = await session.execute(extension_command(extension), params={}) # pyright: ignore[reportDeprecated]
                    await session.commit()
                    self.__extensions_added = True
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def session_dependency(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Session dependency for FastAPI.
        The only difference from `self.session(...)` (beyond logging) is that this function is not decorated as `asynccontextmanager`, since FastAPI wants/needs to do that for us.
        @see https://github.com/tiangolo/fastapi/discussions/9054
        """
        print(f"Before session checkout: {self.pool_status()}")
        async with self.session() as session:
            yield session
        print(f"After session checkout: {self.pool_status()}")

    def pool_status(self):
        # if engine exists
        if hasattr(self, "engine"):
            return self.engine.pool.status()


class LazyDatabase:
    __db: Database | None = None

    def connect(self, **kwargs: Unpack[ConstructorArgs]) -> Database:
        if self.__db is None:
            self.__db = Database(**kwargs)
        return self.__db


def create_all_registered_tables_sync(database: Database):
    SQLModel.metadata.create_all(database.engine.sync_engine)
