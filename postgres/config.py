import os
from typing import Protocol, Literal, Final


class Config(Protocol):
    user: Final[str]
    password: Final[str]
    host: Final[str]
    name: Final[str]


class LocalConnectionConfig:
    """Configuration class for local database connection."""

    user: Final[str] = "postgres"
    password: Final[str] = "postgres"
    host: Final[str] = "localhost:5555"
    name: Final[str] = "postgres"


class ConfigFromEnvironment:
    """Configuration class for database connection from environment variables."""

    user: Final[str]
    password: Final[str]
    host: Final[str]
    name: Final[str]

    def __init__(self) -> None:
        self.user = os.getenv("DB_USER", LocalConnectionConfig.user)
        self.password = os.getenv("DB_PASSWORD", LocalConnectionConfig.password)
        self.host = os.getenv("DB_HOST", LocalConnectionConfig.host)
        self.name = os.getenv("DB_NAME", LocalConnectionConfig.name)


class CustomConfig:
    """Custom configuration class for database connection."""

    user: Final[str]
    password: Final[str]
    host: Final[str]
    name: Final[str]

    def __init__(self, *, user: str, password: str, host: str, name: str):
        self.user = user
        self.password = password
        self.host = host
        self.name = name


PostgresAddOn = Literal["asyncpg", "psycopg"] | None


def config_to_url(config: Config, addon: PostgresAddOn = "asyncpg") -> str:
    driver = "" if addon is None else f"+{addon}"
    return f"postgresql{driver}://{config.user}:{config.password}@{config.host}/{config.name}"
