# pyright: reportMissingParameterType=false
import re

from inflection import underscore

NON_ALPHANUMERIC_OR_UNDERSCORE = re.compile(r"[^a-zA-Z0-9_]")
OPENING_LETTER_OR_UNDERSCORE = re.compile(r"^[a-zA-Z_]")
COMBINED = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def sanitize(tablename: str, preserve_empty=False, automatically_truncate=True) -> str:
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
    sanitized = re.sub(NON_ALPHANUMERIC_OR_UNDERSCORE, "_", tablename)
    if not re.match(OPENING_LETTER_OR_UNDERSCORE, sanitized):
        sanitized = "_" + sanitized
    if automatically_truncate and len(sanitized) > 63:
        sanitized = sanitized[:63]
    if re.match(COMBINED, sanitized):
        return sanitized
    else:
        raise ValueError(
            f"Invalid table name after sanitization. {tablename} -> {sanitized}"
        )


def snake_and_sanitize(tablename: str) -> str:
    """Sanitizes a string to be a valid snake_case name for a SQL table."""
    return underscore(sanitize(tablename))
