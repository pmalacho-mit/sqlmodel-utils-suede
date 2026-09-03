"""How autogenerate compares the models, and how it renders what it finds.

Both entry points -- `run_migrations` and the drift check -- configure alembic
through `migration_options`, so they cannot disagree about what counts as a
difference.
"""

from typing import Any, Literal

from sqlmodel.sql.sqltypes import AutoString

from ..columns import PydanticJSONBType, PydanticJSONType

__all__ = ["migration_options", "render_item"]


def migration_options(**overrides: Any) -> dict[str, Any]:
    """Options for `context.configure()` / `MigrationContext.configure()`.

    Alembic defaults `compare_type` and `compare_server_default` to False, so a
    stock setup silently ignores every column type and default change.
    `compare_server_default` is the noisier of the two: postgres normalises
    defaults on the way in, so an expression can read back differently from how
    it was written.
    """
    return {
        "compare_type": True,
        "compare_server_default": True,
        "render_item": render_item,
        **overrides,
    }


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | Literal[False]:
    """Render one schema object as python source, or False for alembic's default.

    Alembic renders a custom type as `<module>.<Class>(<args it can recover>)`
    and never imports the module. For the types this library ships that means a
    migration file which does not import: `release.columns.PydanticJSONBType(...)`
    is an undefined name, and its required `model_class` argument is gone.
    """
    if type_ != "type":
        return False

    imports: set[str] = autogen_context.imports
    if isinstance(obj, PydanticJSONType):
        return _as_json_column(obj, imports)
    if isinstance(obj, AutoString):
        return _as_varchar(obj)
    return _defer_to_alembic(obj, imports)


def _as_json_column(obj: PydanticJSONType[Any], imports: set[str]) -> str:
    """The JSON or JSONB the database sees.

    The pydantic half of these types is python-only and has no schema footprint,
    so rendering the storage type keeps migrations independent of model classes
    that may be renamed or deleted long before the migration is squashed away.
    """
    if isinstance(obj, PydanticJSONBType):
        imports.add("from sqlalchemy.dialects import postgresql")
        return "postgresql.JSONB(astext_type=sa.Text())"
    return "sa.JSON()"


def _as_varchar(obj: AutoString) -> str:
    """`AutoString` as the VARCHAR it compiles to, keeping sqlmodel out of migrations.

    SQLModel puts `max_length` in the length, so dropping it would quietly widen
    the column to an unbounded VARCHAR.
    """
    length = "" if obj.length is None else f"length={obj.length}"
    return f"sa.String({length})"


def _defer_to_alembic(obj: Any, imports: set[str]) -> Literal[False]:
    """Alembic renders everything else correctly; it just doesn't import it.

    It names a type by the module defining it -- `pgvector.sqlalchemy.vector.VECTOR`,
    not the `pgvector.sqlalchemy.Vector` alias -- so import exactly that one.
    """
    module = type(obj).__module__
    if not module.startswith("sqlalchemy"):
        imports.add(f"import {module}")
    return False
