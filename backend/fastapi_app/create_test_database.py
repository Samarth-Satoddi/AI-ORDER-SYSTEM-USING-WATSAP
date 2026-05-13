import argparse
import os
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.db.base import Base
from fastapi_app.seed import seed

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://hotel:hotel@localhost:5432/hotel_orders_test"


def maintenance_database_url(database_url: str) -> tuple[str, str]:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError("Database URL must include a database name")

    maintenance_url = urlunparse(parsed._replace(path="/postgres", query="", fragment=""))
    return maintenance_url, database_name


def quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def ensure_database(database_url: str, drop_existing: bool = False) -> None:
    maintenance_url, database_name = maintenance_database_url(database_url)
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT", future=True)

    with engine.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
            {"database_name": database_name},
        )

        if exists and drop_existing:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f"DROP DATABASE {quoted_identifier(database_name)}"))
            exists = None

        if not exists:
            connection.execute(text(f"CREATE DATABASE {quoted_identifier(database_name)}"))

    engine.dispose()


def build_test_database(database_url: str, drop_existing: bool = False) -> None:
    ensure_database(database_url, drop_existing=drop_existing)

    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with SessionLocal() as db:
        result = seed(db)

    engine.dispose()
    print(
        "Test database ready: "
        f"{safe_database_label(database_url)}. "
        f"New hotels: {result['hotels']}, new menu items: {result['menu_items']}."
    )


def safe_database_label(database_url: str) -> str:
    parsed = urlparse(database_url)
    host = parsed.hostname or "localhost"
    database_name = parsed.path.lstrip("/")
    return f"{host}/{database_name}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and seed a duplicate test database.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        help="Target PostgreSQL test database URL.",
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop and recreate the test database before seeding.",
    )
    args = parser.parse_args()

    build_test_database(args.database_url, drop_existing=args.drop_existing)


if __name__ == "__main__":
    main()
