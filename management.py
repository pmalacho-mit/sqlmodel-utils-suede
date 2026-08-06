from sqlalchemy.orm.session import Session
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel, Table, delete


def get_table_from_model(model: type[SQLModel]) -> Table:
    return (
        model.__table__  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownVariableType]
    )


async def refresh_all(db: AsyncSession, *models: SQLModel):
    for model in models:
        await db.refresh(model)


async def delete_all(db: AsyncSession, *models: SQLModel):
    for model in models:
        await db.delete(model)


def create_tables_sync(session: Session, tables: list[Table]):
    bind = session.get_bind()
    (
        SQLModel.metadata.create_all(bind, tables)
        if len(tables) > 0
        else SQLModel.metadata.create_all(bind)
    )


async def create_tables_for_models(session: AsyncSession, *models: type[SQLModel]):
    try:
        await session.run_sync(
            create_tables_sync, tables=[get_table_from_model(model) for model in models]
        )
    except Exception as e:
        print(f"Exception trying to create tables for models {models}: {e}")


async def delete_rows_for_models(session: AsyncSession, *models: type[SQLModel]):
    for model in models:
        _ = await session.execute(delete(model))  # pyright: ignore[reportDeprecated]


class ModelTracker:
    session: AsyncSession
    models: list[SQLModel]

    def __init__(self, session: AsyncSession, *models: SQLModel):
        self.session = session
        self.models = list(models)

    def track(self, *models: SQLModel):
        self.models.extend(models)
        return self

    async def refresh(self):
        await refresh_all(self.session, *self.models)
        return self

    async def get_type(self, Model: type[SQLModel]):
        return [model for model in self.models if isinstance(model, Model)]
