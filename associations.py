from abc import ABC as IsAbstractClass
from datetime import datetime, UTC
from uuid import UUID, uuid4
from typing import (
    TypeVar,
    Literal,
    Protocol,
    Any,
)

from sqlmodel import Field, SQLModel, TIMESTAMP
from sqlalchemy.orm import declared_attr

from .utils import TableNameSanitizer

ID = UUID

get_id = uuid4


class WithID(  # pyright: ignore[reportUnsafeMultipleInheritance]
    SQLModel, IsAbstractClass
):
    """A base class for models that have an ID (UUID, specifically)."""

    id: ID = Field(
        default_factory=get_id,
        primary_key=True,
        index=True,
        nullable=False,
        description="Unique identifier for the model (used as primary_key).",
    )
    """The unique identifier for the model (used as primary_key)."""


def now(zone=UTC):
    return datetime.now(zone)


class WithTime(  # pyright: ignore[reportUnsafeMultipleInheritance]
    SQLModel, IsAbstractClass
):
    """A base class for models that have a timestamp (defaults to when model is created)"""

    timestamp: datetime = Field(
        sa_type=TIMESTAMP(timezone=True),  # pyright: ignore[reportArgumentType]
        nullable=False,
        index=True,
        default_factory=now,
        description="The time the model was created.",
    )

    """The time the model was created."""


def compute_tablename(name: str, parts: list[str | None]) -> str:
    name = TableNameSanitizer.SnakeAndSanitize(name)
    # hack for plural table names with class names ending in 'y'
    if len(parts) >= 2 and parts[0] is None and parts[1] == "s" and name[-1] == "y":
        name = name[:-1] + "ie"
    joined = "".join(
        (
            [part if part is not None else name for part in parts]
            if len(parts) > 0
            else [name]
        )
    )
    if len(joined) > 63:
        raise ValueError(
            f"Computed table name '{joined}' is too long. The maximum length is 63 characters. Consider shortening your branch name."
        )
    return joined


class WithTableName(  # pyright: ignore[reportUnsafeMultipleInheritance]
    SQLModel, IsAbstractClass
):
    """A base class for models that specify their own tablename (instead of letting SQLModel do it automatically)."""

    __tablename_parts__: list[str | None] = []
    """The parts of the tablename. If a part is None, it will be replaced with the (lowercase and sanitized) class name."""

    @declared_attr  # pyright: ignore[reportArgumentType]
    def __tablename__(  # pyright: ignore[reportIncompatibleVariableOverride]
        cls,
    ) -> str:
        """The name of the table in the database."""
        return compute_tablename(cls.__name__, cls.__tablename_parts__)

    @classmethod
    def Get_Tablename(cls) -> str:
        return (
            cls.__tablename__
        )  # pyright: ignore[reportUnknownMemberType, reportReturnType, reportUnknownVariableType]


TWithTablename = TypeVar("TWithTablename", bound=WithTableName)

TID = TypeVar("TID")


class HasID(Protocol[TID]):
    id: TID


TWithTableNameAndID = TypeVar("TWithTableNameAndID", bound=WithTableName | HasID[ID])


def get_tablename(table: type[TWithTableNameAndID]):
    withTableName: WithTableName = table  # pyright: ignore[reportAssignmentType]
    return withTableName.Get_Tablename()


def ForeignKeyField(
    table: type[TWithTableNameAndID] | str,
    *,
    nullable: bool = False,
    index: bool = False,
    description: str | None = None,
    ondelete: Literal["CASCADE", "SET NULL", "RESTRICT"] | None = "CASCADE",
) -> Any:
    """Creates a foreign key field for the given table.

    Note: It is critical that consumers of this function explicitly type the property as `ID`
    to ensure correct typing and behavior with SQLModel/SQLAlchemy.
    """

    if isinstance(table, str):
        clsName = table
        tableName = table
    else:
        clsName = table.__name__
        tableName = get_tablename(table)

    foreign_key = f"{tableName}.id"

    description = (
        description or f"The id of the associated {clsName} model (table: {tableName})."
    )

    if ondelete is None:
        return Field(
            foreign_key=foreign_key,
            nullable=nullable,
            index=index,
            description=description,
        )
    elif ondelete == "SET NULL":
        if nullable:
            return Field(
                foreign_key=foreign_key,
                nullable=True,
                index=index,
                description=description,
                ondelete="SET NULL",
            )
        else:
            raise ValueError(
                f"Cannot set ondelete='SET NULL' for non-nullable foreign key to {clsName}."
            )
    else:
        return Field(
            foreign_key=foreign_key,
            nullable=nullable,
            index=index,
            description=description,
            ondelete=ondelete,
        )
