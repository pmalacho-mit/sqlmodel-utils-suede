import re

from inflection import underscore
from sqlmodel import text
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.engine import ScalarResult


class TableNameSanitizer:
    """A utility class for sanitizing table names for SQL databases."""

    non_alphanumeric_or_underscore = re.compile(r"[^a-zA-Z0-9_]")
    opening_letter_or_underscore = re.compile(r"^[a-zA-Z_]")
    combined = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    @classmethod
    def Sanitize(
        cls, tablename: str, preserve_empty=False, automatically_truncate=True
    ) -> str:
        """
        Sanitizes a string to be a valid name for a SQL table.

        Args:
            tablename (str): The table name to be sanitized.
            preserve_empty (bool, optional): Whether to preserve an empty string as the table name. Defaults to False.
            automatically_truncate (bool, optional): Whether to automatically truncate the table name to 63 characters (max length for PostgreSQL). Defaults to True.

        Raises:
            ValueError: If the table name is invalid after sanitization.
        """
        if tablename == "" and preserve_empty:
            return tablename
        sanitized = re.sub(cls.non_alphanumeric_or_underscore, "_", tablename)
        if not re.match(cls.opening_letter_or_underscore, sanitized):
            sanitized = "_" + sanitized
        if automatically_truncate and len(sanitized) > 63:
            sanitized = sanitized[:63]
        if re.match(cls.combined, sanitized):
            return sanitized
        else:
            raise ValueError(
                f"Invalid table name after sanitization. {tablename} -> {sanitized}"
            )

    @classmethod
    def SnakeAndSanitize(cls, tablename: str) -> str:
        """Sanitizes a string to be a valid snake_case name for a SQL table."""
        return underscore(cls.Sanitize(tablename))


async def get_all_table_names_result_from_db(
    session: AsyncSession,
) -> ScalarResult[tuple[str, ...]]:
    statement = text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )

    return await session.execute(statement)  # pyright: ignore[reportReturnType,reportDeprecated]