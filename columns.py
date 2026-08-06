import enum
from typing import Any, Literal, TypeVar, cast, overload, override

from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator, JSON, TypeEngine
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum, Field

T = TypeVar("T", bound=BaseModel)
V = TypeVar("V")
E = TypeVar("E", bound=enum.Enum)


class PydanticJSONType(TypeDecorator[V]):
    """
    Stores a pydantic model (or a list of them) in a JSON column.

    Note: like any JSON column, in-place mutation of the value (e.g.
    `instance.highlights.append(...)`) is not tracked by SQLAlchemy.
    Re-assign the attribute to flag the column as dirty.
    """

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = JSON
    cache_ok: bool | None = True

    def __init__(
        self,
        model_class: type[BaseModel],
        is_list: bool = False,
        none_as_null: bool = True,
        **kwargs: Any,
    ) -> None:
        # These are stored under their constructor argument names so that
        # SQLAlchemy folds them into the type's cache key (see
        # TypeEngine._static_cache_key), which is what makes `cache_ok = True`
        # safe here. Anything else must stay underscore-prefixed.
        self.model_class: type[BaseModel] = model_class
        self.is_list: bool = is_list
        # SQLAlchemy's JSON default (False) writes a *JSON* null for `None`, so a
        # nullable column never actually holds SQL NULL and `IS NULL` never
        # matches. For a column holding a model, None means "no value".
        self.none_as_null: bool = none_as_null
        self._adapter: TypeAdapter[Any] = TypeAdapter(
            list[model_class] if is_list else model_class  # type: ignore[valid-type]
        )
        super().__init__(none_as_null=none_as_null, **kwargs)

    @override
    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        # validate first so raw dicts (and other coercible input) are accepted,
        # then dump in "json" mode so datetimes/UUIDs/enums are JSON-safe.
        return self._adapter.dump_python(
            self._adapter.validate_python(value), mode="json"
        )

    @override
    def process_result_value(self, value: Any, dialect: Dialect) -> V | None:
        if value is None:
            return None
        return self._adapter.validate_python(value)


class PydanticJSONBType(PydanticJSONType[V]):
    """`PydanticJSONType`, backed by postgres JSONB (falls back to JSON elsewhere)."""

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = JSONB
    cache_ok: bool | None = True

    @override
    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB(none_as_null=self.none_as_null))
        return dialect.type_descriptor(JSON(none_as_null=self.none_as_null))


@overload
def PydanticAsJSONColumn(
    model_class: type[T], is_list: Literal[False] = False, **kwargs: Any
) -> PydanticJSONType[T]: ...


@overload
def PydanticAsJSONColumn(
    model_class: type[T], is_list: Literal[True], **kwargs: Any
) -> PydanticJSONType[list[T]]: ...


def PydanticAsJSONColumn(
    model_class: type[T], is_list: bool = False, **kwargs: Any
) -> PydanticJSONType[Any]:
    """
    A JSON column type that round-trips `model_class` instances.

    >>> Field(sa_column=Column(PydanticAsJSONColumn(Highlight, is_list=True), nullable=True))
    """
    return PydanticJSONType(model_class, is_list=is_list, **kwargs)


@overload
def PydanticAsJSONBColumn(
    model_class: type[T], is_list: Literal[False] = False, **kwargs: Any
) -> PydanticJSONBType[T]: ...


@overload
def PydanticAsJSONBColumn(
    model_class: type[T], is_list: Literal[True], **kwargs: Any
) -> PydanticJSONBType[list[T]]: ...


def PydanticAsJSONBColumn(
    model_class: type[T], is_list: bool = False, **kwargs: Any
) -> PydanticJSONBType[Any]:
    """
    A JSONB column type that round-trips `model_class` instances.

    >>> Field(sa_column=Column(PydanticAsJSONBColumn(Highlight, is_list=True), nullable=True))
    """
    return PydanticJSONBType(model_class, is_list=is_list, **kwargs)


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    """
    The values persisted for an enum. We store `.value` rather than the default
    `.name`, so renaming a member is a code-only change.
    """
    return [member.value for member in enum_class]


def EnumField(
    enum_class: type[E],
    *,
    default: Any = PydanticUndefined,
    nullable: bool = False,
    index: bool = False,
    unique: bool = False,
    name: str | None = None,
    native_enum: bool = True,
    **field_kwargs: Any,
) -> E:
    """
    A column storing `enum_class` by value.

    `name` overrides the generated DB type name (defaults to the lowercased class
    name, which collides if two enums share a name). `native_enum=False` stores a
    VARCHAR + CHECK constraint instead of a postgres ENUM type, which avoids
    `ALTER TYPE` migrations when members change. `nullable=True` implies
    `default=None`. Remaining kwargs go to `Field` (description, alias, ...).

    >>> status: Status = EnumField(Status, default=Status.PENDING, index=True)
    """
    if default is PydanticUndefined and nullable:
        default = None

    enum_type = Enum(
        enum_class,
        values_callable=enum_values,
        native_enum=native_enum,
        **({"name": name} if name else {}),
    )

    return Field(
        default=default,
        nullable=nullable,
        index=index,
        unique=unique,
        # `sa_type` (not `sa_column`) so SQLModel builds a fresh Column per model:
        # a Column instance can only be attached to one Table, so an `EnumField`
        # declared on a shared base class would fail on the second subclass.
        #
        # SQLModel annotates `sa_type` as `type[Any]`, but hands it straight to
        # `Column(...)`, which takes a TypeEngine instance just as happily as a
        # class -- hence the cast.
        sa_type=cast(type[Enum], enum_type),
        **field_kwargs,  # pyright: ignore[reportAny]
    )
