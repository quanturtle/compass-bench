"""Engines and explicit migration. Startup never migrates."""

from pathlib import Path
from typing import Final

import psycopg
import sqlalchemy
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

DRIVER_SCHEME: Final = "postgresql+psycopg://"
ACCEPTED_SCHEMES: Final = ("postgresql://", "postgres://", DRIVER_SCHEME)
MIGRATIONS_DIRECTORY: Final = Path(__file__).parent / "migrations"


class InvalidDatabaseUrl(Exception):
    """The database URL is neither a postgresql:// URL nor libpq conninfo."""


def parsed_url(url: str) -> str:
    """The URL once SQLAlchemy parses it; its own error would quote the URL, so the cause is dropped."""
    try:
        sqlalchemy.make_url(url)
    except ValueError, sqlalchemy.exc.ArgumentError:
        raise InvalidDatabaseUrl("the database URL does not parse; check its host and port") from None
    return url


def driver_arguments(database_url: SecretStr) -> tuple[str, dict[str, object]]:
    """The SQLAlchemy URL and connect arguments; conninfo becomes psycopg's keyword parameters."""
    text = database_url.get_secret_value().strip()
    for scheme in ACCEPTED_SCHEMES:
        if text.startswith(scheme):
            return parsed_url(DRIVER_SCHEME + text.removeprefix(scheme)), {}
    if "://" in text:
        raise InvalidDatabaseUrl(f"the database URL must start with one of {', '.join(ACCEPTED_SCHEMES)}")
    try:
        return DRIVER_SCHEME, dict(conninfo_to_dict(text))
    except psycopg.ProgrammingError as error:
        raise InvalidDatabaseUrl("the database URL is not valid libpq conninfo") from error


def create_engine(database_url: SecretStr) -> AsyncEngine:
    """Accepts postgresql://, postgres://, and libpq conninfo; the password never reaches a log."""
    url, connect_args = driver_arguments(database_url)
    return create_async_engine(url, connect_args=connect_args, hide_parameters=True, pool_pre_ping=True)


def upgrade_to_head(database_url: SecretStr) -> None:
    """Run Alembic to head; the one database role owns the schema."""
    url, connect_args = driver_arguments(database_url)
    engine = sqlalchemy.create_engine(url, connect_args=connect_args, hide_parameters=True)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    engine.dispose()
    return
