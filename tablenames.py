from typing import TypeAlias, overload, Literal, NamedTuple
from uuid import uuid4

from .associations import WithTableName, compute_tablename
from .sanitize import sanitize


def tablename_mixin(*parts: str | None) -> type[WithTableName]:
    """
    Creates a mixin class with a dynamically generated table name based on the provided parts.

    Args:
        *parts: Variable number of strings or None values representing the parts of the table name (joined together via the empty string).

    Returns:
        A dynamically generated mixin class with a table name derived from the provided parts.
    """
    class_name = f"{WithTableName.__name__}_{'_'.join([part for part in parts if part is not None])}" # fmt: skip
    class_attrs = {
        "__tablename_parts__": [
            sanitize(part, True) if part is not None else None for part in parts
        ]
    }
    return type(class_name, (WithTableName,), class_attrs)


Settings: TypeAlias = Literal["plural", "uuid", "custom", "singular"]


def parts_from_setting(setting: Settings, name: str | None = None) -> list[str | None]:
    if setting == "plural":
        return [None, "s"]
    elif setting == "singular":
        return [None]
    elif setting == "uuid":
        return [None, str(uuid4()).replace("-", "")]
    elif setting == "custom":
        if name is None:
            raise ValueError("Custom table name requires a name to be provided.")
        return [name]


@overload
def tablename(setting: Literal["singular"]) -> type[WithTableName]:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be the plural form of the classname (as well as 'sanitized').
    """
    ...


@overload
def tablename(setting: Literal["plural"]) -> type[WithTableName]:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be the plural form of the classname (as well as 'sanitized').
    """
    ...


@overload
def tablename(setting: Literal["uuid"]) -> type[WithTableName]:
    """
    Names the corresponding table (i.e. `__tablename__` property) to have a trailing UUID after the classname (as well as 'sanitized').
    """
    ...


@overload
def tablename(setting: Literal["custom"], name: str) -> type[WithTableName]:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be a custom string (as well as 'sanitized').
    """
    ...


def tablename(setting: Settings, name: str | None = None) -> type[WithTableName]:
    return tablename_mixin(*parts_from_setting(setting, name))


def computed_tablename(cls: str, setting: Settings, name: str | None = None) -> str:
    """
    Computes what a tablename will becomoe when using the `tablename` mixin.

    This is useful for when you need to reference a table name before the class is defined,
    such as when defining a foreign key relationship to one's self.

    But CAUTION: It is your responisbility to keep the `cls` parameter in sync with the actualy name of your file
    """
    return compute_tablename(cls, parts_from_setting(setting, name))


class ExplicitTablename(NamedTuple):
    tablename: str
    mixin: type[WithTableName]


@overload
def explicit_tablename(cls: str, setting: Literal["singular"]) -> ExplicitTablename:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be the plural form of the classname (as well as 'sanitized').
    """
    ...


@overload
def explicit_tablename(cls: str, setting: Literal["plural"]) -> ExplicitTablename:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be the plural form of the classname (as well as 'sanitized').
    """
    ...


@overload
def explicit_tablename(cls: str, setting: Literal["uuid"]) -> ExplicitTablename:
    """
    Names the corresponding table (i.e. `__tablename__` property) to have a trailing UUID after the classname (as well as 'sanitized').
    """
    ...


@overload
def explicit_tablename(
    cls: str, setting: Literal["custom"], name: str
) -> ExplicitTablename:
    """
    Names the corresponding table (i.e. `__tablename__` property) to be a custom string (as well as 'sanitized').
    """
    ...


def explicit_tablename(
    cls: str, setting: Settings, name: str | None = None
) -> ExplicitTablename:
    parts = parts_from_setting(setting, name)
    custom = compute_tablename(cls, parts)
    return ExplicitTablename(
        tablename=custom,
        mixin=tablename("custom", custom),
    )
