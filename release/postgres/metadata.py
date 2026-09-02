"""Shared SQLAlchemy metadata with consistent constraint naming conventions.

Two ways to use this module:

1. **Recommended:** have your table models inherit from :class:`Base`
   instead of ``sqlmodel.SQLModel``. Each model then registers into
   ``Base.metadata``, which carries the naming conventions, and ordering
   of imports does not matter.

2. **Migration path:** if you already have models inheriting directly from
   ``SQLModel`` and don't want to change them, call
   :func:`install_global_naming_conventions` once at startup, *before* any
   ``table=True`` model is defined. It replaces ``SQLModel.metadata`` and
   raises if models have already been registered, because those tables
   would otherwise be stranded in the old metadata object.

In both cases, point Alembic at the right object in ``env.py``::

    target_metadata = Base.metadata          # option 1
    target_metadata = SQLModel.metadata      # option 2
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import registry
from sqlmodel import SQLModel

__all__ = [
    "NAMING_CONVENTION",
    "new_metadata",
    "Base",
    "install_global_naming_conventions",
]

#: Constraint naming conventions, matching PostgreSQL's default names so that
#: reflected and generated schemas agree. See
#: https://docs.sqlalchemy.org/en/20/core/constraints.html#configuring-constraint-naming-conventions
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


def new_metadata() -> MetaData:
    """Return a fresh, empty ``MetaData`` using :data:`NAMING_CONVENTION`."""
    return MetaData(naming_convention=NAMING_CONVENTION)


class Base(SQLModel, registry=registry(metadata=new_metadata())):
    """Base class for table models that should share the named metadata.

    Models must inherit from ``Base`` (not ``SQLModel``) to be included in
    ``Base.metadata``. A model that inherits from ``SQLModel`` directly will
    register into ``SQLModel.metadata`` instead and will be invisible to
    ``Base.metadata.create_all()`` and to Alembic when ``target_metadata``
    is ``Base.metadata``.

    Non-table models (schemas, DTOs) can inherit from either base; they are
    never registered in any metadata.
    """


def install_global_naming_conventions() -> MetaData:
    """Replace ``SQLModel.metadata`` with one using :data:`NAMING_CONVENTION`.

    Must be called before any ``table=True`` model inheriting directly from
    ``SQLModel`` is defined. Models defined earlier stay bound to the old
    metadata and would be lost, so this raises instead of proceeding.

    Calling it again after a successful install is a no-op.

    Returns:
        The metadata now installed on ``SQLModel``.
    """
    current = SQLModel.metadata
    if current.naming_convention == NAMING_CONVENTION:
        return current
    if current.tables:
        raise RuntimeError(
            "SQLModel.metadata already contains tables "
            + f"{sorted(current.tables)}; call install_global_naming_conventions() "
            + "before defining any table models, or inherit from Base instead."
        )

    SQLModel.metadata = new_metadata()
    return SQLModel.metadata
