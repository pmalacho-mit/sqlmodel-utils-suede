from sqlmodel import text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.engine import ScalarResult


async def get_all_table_names_result_from_db(
    session: AsyncSession,
) -> ScalarResult[tuple[str, ...]]:
    statement = text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )

    return await session.execute( # pyright: ignore[reportReturnType,reportDeprecated]
        statement
    ) 
