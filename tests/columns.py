"""Tests for `release/columns.py`, against a real postgres."""

import enum
from datetime import datetime, timezone
from collections.abc import Sequence
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, Enum, Inspector, Row, text
from sqlalchemy.exc import StatementError
from sqlmodel import Column, Field, Session, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from release.columns import (
    EnumField,
    PydanticAsJSONBColumn,
    PydanticAsJSONColumn,
    PydanticJSONBType,
    PydanticJSONType,
)


class Highlight(BaseModel):
    start_line: int
    end_line: int
    note: str | None = None
    seen_at: datetime | None = None


class Point(BaseModel):
    x: int
    y: int


class Status(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in progress"
    DONE = "done"


class JSONRow(SQLModel, table=True):
    __tablename__ = "json_row"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    one: Highlight | None = Field(
        default=None,
        sa_column=Column(PydanticAsJSONColumn(Highlight), nullable=True),
    )
    many: list[Highlight] | None = Field(
        default=None,
        sa_column=Column(PydanticAsJSONColumn(Highlight, is_list=True), nullable=True),
    )


class JSONBRow(SQLModel, table=True):
    __tablename__ = "jsonb_row"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    one: Point | None = Field(
        default=None,
        sa_column=Column(PydanticAsJSONBColumn(Point), nullable=True),
    )
    many: list[Point] | None = Field(
        default=None,
        sa_column=Column(PydanticAsJSONBColumn(Point, is_list=True), nullable=True),
    )


class HasStatus(SQLModel):
    """A shared base -- the case that a `sa_column`-based EnumField cannot serve."""

    status: Status = EnumField(Status, default=Status.PENDING, index=True)


class EnumRowA(HasStatus, table=True):
    __tablename__ = "enum_row_a"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)


class EnumRowB(HasStatus, table=True):
    __tablename__ = "enum_row_b"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    review: Status | None = EnumField(Status, nullable=True, name="review_status")
    label: Status = EnumField(
        Status, default=Status.DONE, native_enum=False, unique=True
    )


def query(engine: Engine, sql: str, **params: Any) -> Sequence[Row[Any]]:
    """Read back through raw SQL, i.e. bypassing the type decorator entirely."""
    with engine.connect() as connection:
        return connection.execute(text(sql), params).all()


def scalar(engine: Engine, sql: str, **params: Any) -> Any:
    return query(engine, sql, **params)[0][0]


# --------------------------------------------------------------------------
# PydanticAsJSONColumn / PydanticAsJSONBColumn
# --------------------------------------------------------------------------


def test_single_model_round_trips(session: Session):
    session.add(JSONRow(id=1, one=Highlight(start_line=1, end_line=4, note="hi")))
    session.commit()
    session.expunge_all()

    row = session.exec(select(JSONRow)).one()
    assert isinstance(row.one, Highlight)
    assert row.one == Highlight(start_line=1, end_line=4, note="hi")


def test_list_of_models_round_trips(session: Session):
    highlights = [
        Highlight(start_line=1, end_line=2),
        Highlight(start_line=8, end_line=9),
    ]
    session.add(JSONRow(id=1, many=highlights))
    session.commit()
    session.expunge_all()

    row = session.exec(select(JSONRow)).one()
    assert row.many == highlights
    assert all(isinstance(item, Highlight) for item in row.many or [])


def test_empty_list_is_preserved(session: Session):
    """`[]` must survive as `[]` -- not collapse to NULL the way a falsy check would."""
    session.add(JSONRow(id=1, many=[]))
    session.commit()
    session.expunge_all()

    assert session.exec(select(JSONRow)).one().many == []


def test_datetime_is_serialized(session: Session, engine: Engine):
    """`model_dump()` alone leaves a datetime object the JSON encoder rejects."""
    seen_at = datetime(2026, 8, 6, 12, 30, tzinfo=timezone.utc)
    session.add(JSONRow(id=1, one=Highlight(start_line=1, end_line=2, seen_at=seen_at)))
    session.commit()
    session.expunge_all()

    stored = scalar(engine, "select one->>'seen_at' from json_row")
    assert isinstance(stored, str)
    assert datetime.fromisoformat(stored) == seen_at

    row = session.exec(select(JSONRow)).one()
    assert row.one is not None and row.one.seen_at == seen_at


def test_raw_dicts_are_accepted_and_come_back_as_models(session: Session):
    raw = {"start_line": 1, "end_line": 2}
    session.add(JSONRow(id=1, one=raw))  # pyright: ignore[reportArgumentType]
    session.commit()
    session.expunge_all()

    row = session.exec(select(JSONRow)).one()
    assert row.one == Highlight(start_line=1, end_line=2)


def test_invalid_payload_is_rejected(session: Session):
    """A bad payload fails on the way in, rather than at some later read."""
    incomplete = {"start_line": 1}
    session.add(JSONRow(id=1, one=incomplete))  # pyright: ignore[reportArgumentType]
    with pytest.raises(StatementError) as failure:
        session.commit()
    assert isinstance(failure.value.orig, ValidationError)
    session.rollback()


def test_none_is_stored_as_sql_null(session: Session, engine: Engine):
    """Not a JSON `null`, so `IS NULL` and `nullable=True` mean what they say."""
    session.add(JSONRow(id=1))
    session.commit()
    session.expunge_all()

    assert scalar(engine, "select count(*) from json_row where one is null") == 1
    row = session.exec(select(JSONRow)).one()
    assert row.one is None and row.many is None


def test_json_column_is_json_and_jsonb_column_is_jsonb(inspector: Inspector):
    def udt(table: str, column: str) -> str:
        found = next(c for c in inspector.get_columns(table) if c["name"] == column)
        return str(found["type"]).lower()

    assert udt("json_row", "one") == "json"
    assert udt("json_row", "many") == "json"
    assert udt("jsonb_row", "one") == "jsonb"
    assert udt("jsonb_row", "many") == "jsonb"


def test_jsonb_supports_containment_queries(session: Session, engine: Engine):
    """`@>` is jsonb-only -- it fails outright against a json column."""
    session.add(JSONBRow(id=1, one=Point(x=1, y=2)))
    session.add(JSONBRow(id=2, one=Point(x=9, y=9)))
    session.commit()

    matched = query(
        engine, """select id from jsonb_row where one @> '{"x": 1}'::jsonb"""
    )
    assert [row[0] for row in matched] == [1]


def test_jsonb_round_trips(session: Session):
    session.add(JSONBRow(id=1, one=Point(x=1, y=2), many=[Point(x=3, y=4)]))
    session.commit()
    session.expunge_all()

    row = session.exec(select(JSONBRow)).one()
    assert row.one == Point(x=1, y=2)
    assert row.many == [Point(x=3, y=4)]


# --------------------------------------------------------------------------
# type caching -- `cache_ok = True` is only safe if the parameters reach the key
# --------------------------------------------------------------------------


def test_cache_key_covers_every_parameter():
    keys = {
        "json list": PydanticAsJSONColumn(Highlight, is_list=True)._static_cache_key,
        "json single": PydanticAsJSONColumn(Highlight)._static_cache_key,
        "json other model": PydanticAsJSONColumn(Point, is_list=True)._static_cache_key,
        "jsonb list": PydanticAsJSONBColumn(Highlight, is_list=True)._static_cache_key,
    }
    assert len(set(keys.values())) == len(keys), "distinct types share a cache key"


def test_cache_key_is_stable_for_equivalent_types():
    left = PydanticAsJSONColumn(Highlight, is_list=True)
    right = PydanticAsJSONColumn(Highlight, is_list=True)
    assert left._static_cache_key == right._static_cache_key


def test_factories_return_usable_type_instances():
    """Not a `typing` alias -- `Column(...)` needs a real TypeEngine."""
    assert isinstance(PydanticAsJSONColumn(Highlight), PydanticJSONType)
    assert isinstance(PydanticAsJSONBColumn(Point), PydanticJSONBType)


# --------------------------------------------------------------------------
# EnumField
# --------------------------------------------------------------------------


def test_enum_round_trips(session: Session):
    session.add(EnumRowA(id=1, status=Status.IN_PROGRESS))
    session.commit()
    session.expunge_all()

    assert session.exec(select(EnumRowA)).one().status is Status.IN_PROGRESS


def test_enum_persists_values_not_names(session: Session, engine: Engine):
    session.add(EnumRowA(id=1, status=Status.IN_PROGRESS))
    session.commit()

    assert scalar(engine, "select status::text from enum_row_a") == "in progress"


def test_enum_type_labels_are_values(engine: Engine):
    labels = query(
        engine,
        """
        select enumlabel from pg_enum
        join pg_type on pg_type.oid = pg_enum.enumtypid
        where typname = 'status' order by enumsortorder
        """,
    )
    assert [row[0] for row in labels] == [member.value for member in Status]


def test_enum_can_be_declared_on_a_shared_base(session: Session):
    """The regression: one `sa_column` cannot attach to two tables."""
    session.add(EnumRowA(id=1))
    session.add(EnumRowB(id=1))
    session.commit()
    session.expunge_all()

    assert session.exec(select(EnumRowA)).one().status is Status.PENDING
    assert session.exec(select(EnumRowB)).one().status is Status.PENDING


def test_enum_default_is_applied(session: Session):
    session.add(EnumRowB(id=1))
    session.commit()
    session.expunge_all()

    row = session.exec(select(EnumRowB)).one()
    assert row.status is Status.PENDING
    assert row.label is Status.DONE


def test_nullable_enum_defaults_to_none(session: Session, engine: Engine):
    session.add(EnumRowB(id=1))
    session.commit()

    assert scalar(engine, "select count(*) from enum_row_b where review is null") == 1


def test_enum_filters_by_member(session: Session):
    session.add(EnumRowA(id=1, status=Status.DONE))
    session.add(EnumRowA(id=2, status=Status.PENDING))
    session.commit()

    found = session.exec(select(EnumRowA).where(EnumRowA.status == Status.DONE)).all()
    assert [row.id for row in found] == [1]


def test_enum_type_name_can_be_overridden(inspector: Inspector):
    column = next(
        c for c in inspector.get_columns("enum_row_b") if c["name"] == "review"
    )
    assert cast(Enum, column["type"]).name == "review_status"


def test_non_native_enum_is_a_varchar(inspector: Inspector):
    column = next(
        c for c in inspector.get_columns("enum_row_b") if c["name"] == "label"
    )
    assert "VARCHAR" in str(column["type"]).upper()


def test_enum_column_flags_reach_the_table(inspector: Inspector):
    assert any(
        index["column_names"] == ["status"]
        for index in inspector.get_indexes("enum_row_a")
    ), "index=True was dropped"
    assert any(
        constraint["column_names"] == ["label"]
        for constraint in inspector.get_unique_constraints("enum_row_b")
    ), "unique=True was dropped"


def test_enum_column_nullability(inspector: Inspector):
    columns = {c["name"]: c for c in inspector.get_columns("enum_row_b")}
    assert columns["status"]["nullable"] is False
    assert columns["review"]["nullable"] is True


# --------------------------------------------------------------------------
# the same columns over asyncpg, the driver `Database` actually ships with.
# It registers its own json/jsonb codecs and needs explicit bind casts, so it
# is a genuinely different path from psycopg -- not a repeat of the above.
# --------------------------------------------------------------------------


async def test_async_session_really_is_asyncpg(async_session: AsyncSession):
    """Guards the block below: without this it could all quietly run on psycopg."""
    assert async_session.get_bind().dialect.driver == "asyncpg"


async def test_json_round_trips_over_asyncpg(async_session: AsyncSession):
    async_session.add(JSONRow(id=1, one=Highlight(start_line=1, end_line=4)))
    await async_session.commit()

    row = (await async_session.exec(select(JSONRow))).one()
    assert row.one == Highlight(start_line=1, end_line=4)


async def test_json_list_round_trips_over_asyncpg(async_session: AsyncSession):
    highlights = [Highlight(start_line=1, end_line=2, note="a")]
    async_session.add(JSONRow(id=1, many=highlights))
    await async_session.commit()

    row = (await async_session.exec(select(JSONRow))).one()
    assert row.many == highlights


async def test_jsonb_round_trips_over_asyncpg(async_session: AsyncSession):
    async_session.add(JSONBRow(id=1, one=Point(x=1, y=2), many=[Point(x=3, y=4)]))
    await async_session.commit()

    row = (await async_session.exec(select(JSONBRow))).one()
    assert row.one == Point(x=1, y=2)
    assert row.many == [Point(x=3, y=4)]


async def test_null_round_trips_over_asyncpg(async_session: AsyncSession):
    async_session.add(JSONRow(id=1))
    await async_session.commit()

    row = (await async_session.exec(select(JSONRow))).one()
    assert row.one is None and row.many is None


async def test_native_enum_round_trips_over_asyncpg(async_session: AsyncSession):
    """asyncpg is strict about enum binds -- it needs the cast SQLAlchemy renders."""
    async_session.add(EnumRowA(id=1, status=Status.IN_PROGRESS))
    await async_session.commit()

    row = (await async_session.exec(select(EnumRowA))).one()
    assert row.status is Status.IN_PROGRESS


async def test_enum_filters_by_member_over_asyncpg(async_session: AsyncSession):
    async_session.add(EnumRowB(id=1, status=Status.DONE, review=Status.PENDING))
    await async_session.commit()

    statement = select(EnumRowB).where(EnumRowB.review == Status.PENDING)
    row = (await async_session.exec(statement)).one()
    assert row.status is Status.DONE
    assert row.label is Status.DONE
