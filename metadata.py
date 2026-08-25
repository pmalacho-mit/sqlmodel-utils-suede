from sqlalchemy import MetaData
from sqlmodel import SQLModel

SQLModel.metadata = MetaData(
    naming_convention={
        # indexes
        "ix": "ix_%(column_0_label)s",
        # unique constraints
        "uq": "%(table_name)s_%(column_0_name)s_key",
        # check constraints
        "ck": "%(table_name)s_%(constraint_name)s_check",
        # foreign keys
        "fk": "%(table_name)s_%(column_0_name)s_fkey",
        # primary keys
        "pk": "%(table_name)s_pkey",
    }
)