# pyright: reportExplicitAny=false, reportMissingParameterType=false
from abc import ABC as IsAbstractClass
from collections.abc import Coroutine
from typing import Any, Callable, TypeVar, Self

from sqlalchemy import ScalarResult
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.exc import IntegrityError

from .management import refresh_all
from .associations import WithID, get_id

TSomeModel = TypeVar("TSomeModel", bound=SQLModel)


async def try_create(
    db: AsyncSession, element: TSomeModel, raise_on_exception=False
) -> TSomeModel | None:
    """Tries to add an element to the database and returns it if successful."""
    try:
        db.add(element)
        await db.commit()
        await db.refresh(element)
        return element
    except Exception as e:
        print(f"Error trying to add {str(element)[:200]}: {str(e)[:200]}")
        await db.rollback()
        if raise_on_exception:
            raise e
        return None


async def try_create_all(
    db: AsyncSession, *elements: TSomeModel, raise_on_exception=False
) -> list[TSomeModel] | None:
    """Tries to add an element to the database and returns it if successful."""
    try:
        db.add_all(elements)
        await db.commit()
        await refresh_all(db, *elements)
        return list(elements)
    except Exception as e:
        print(f"Error trying to add {str(elements)[:200]}: {str(e)[:200]}")
        await db.rollback()
        if raise_on_exception:
            raise e
        return None


TSomeModelWithID = TypeVar("TSomeModelWithID", bound=WithID)


async def repeated_try_create(
    db: AsyncSession, element: TSomeModelWithID, max_attempts=5
) -> TSomeModelWithID | None:
    """Tries to add an element to the database and returns it if successful."""
    for _ in range(max_attempts):
        try:
            attempt = await try_create(db, element, True)
            if attempt is not None:
                return element
            raise Exception
        except IntegrityError:
            print(
                f"IntegrityError raised when trying to add {str(element)[:100]}. Retrying with new id..."
            )
            element.id = get_id()
            continue
        except Exception as e:
            raise Exception(
                f"Unexpected exception raised when trying to add {str(element)[:100]}: {str(e)[:200]}"
            )
    return None


DEFAULT_TRY_CREATE_MAX_ATTEMPTS = 5


class Factory(WithID, IsAbstractClass):
    """
    A mixin class for adding helpful creation and accessor class
    (ie static) methods to model classes.

    This allows you to then take advantage of the class methods provided by this mixin class, like so:
    ```python
        instance = await MyClass.Try_Create(session, MyClass())
    ```
    """

    @classmethod
    def Get(
        cls, db_session: AsyncSession, *conditions: Callable[[type[Self]], bool]
    ) -> Coroutine[Any, Any, ScalarResult[Self]]:
        """
        Gets an instance of the derived class with the given condition(s) (asynchronously).

        NOTE: The condition paramater is a variable number of lambdas
        that take the derived class as a parameter and return a boolean.
        The reasons it accepts one or more lambdas lambda is because `and` & `or`
        operations in a single lambda seem to not play nicely with SQL Model WHERE clauses.
        """
        if len(conditions) == 0:
            return db_session.exec(select(cls))
        query = select(cls)
        for condition in conditions:
            query = query.where(condition(cls))
        return db_session.exec(query)

    @classmethod
    def Try_Create(
        cls,
        db_session: AsyncSession,
        instance: Self,
        max_attempts=DEFAULT_TRY_CREATE_MAX_ATTEMPTS,
    ) -> Coroutine[Any, Any, Self | None]:
        """
        Tries to add an instance of the derived class to the database and returns it if successful.
        """
        return repeated_try_create(
            db_session,
            instance,
            max_attempts,
        )

    @classmethod
    def Try_Create_All(
        cls, db_session: AsyncSession, *instances: Self
    ) -> Coroutine[Any, Any, list[Self] | None]:
        """
        Tries to add an instance of the derived class to the database and returns it if successful.
        """
        return try_create_all(db_session, *instances)

    @classmethod
    async def Try_Get_Single(
        cls, db_session: AsyncSession, *conditions: Callable[[type[Self]], bool]
    ) -> Self | None:
        """
        Tries to get an instance of the derived class with the given condition(s).

        NOTE: The condition paramater is a variable number of lambdas that take the derived class as a parameter and return a boolean.
        The reasons it accepts one or more lambdas lambda is because `and` and `or` operations in a single lambda seem to not play nicely with SQL Model WHERE clauses.
        """
        query = await cls.Get(db_session, *conditions)
        return query.first()

    @classmethod
    async def Get_Or_Create(
        cls,
        db_session: AsyncSession,
        instance: Self,
        *conditions: Callable[[type[Self]], bool],
    ) -> Self:
        """
        Gets or creates an instance of the derived class with the given condition and instance.

        NOTE: The condition paramater is a variable number of lambdas that take the derived class as a parameter and return a boolean.
        The reasons it accepts one or more lambdas is because `and` and `or` operations in a single lambda seem to not play nicely with SQL Model WHERE clauses.
        """
        result = await cls.Try_Get_Single(db_session, *conditions)
        result = (
            result if result is not None else await cls.Try_Create(db_session, instance)
        )
        if result is None:
            raise ValueError(f"Failed to create {cls.__name__}")
        return result

    @classmethod
    async def Delete(cls, db_session: AsyncSession, *instances: Self) -> None:
        """
        Deletes the given instances of the derived class.
        """
        try:
            for instance in instances:
                await db_session.delete(instance)
            await db_session.commit()
        except Exception as e:
            print(f"Error trying to delete {str(instances)[:100]}: {str(e)[:200]}")
            await db_session.rollback()

    async def delete(self, db_session: AsyncSession) -> None:
        await self.Delete(db_session, self)

    async def try_create(
        self, db_session: AsyncSession, max_attemps=DEFAULT_TRY_CREATE_MAX_ATTEMPTS
    ) -> Self | None:
        return await self.Try_Create(db_session, self, max_attemps)

    async def get_or_create(
        self, db_session: AsyncSession, *conditions: Callable[[type[Self]], bool]
    ) -> Self:
        return await self.Get_Or_Create(db_session, self, *conditions)
