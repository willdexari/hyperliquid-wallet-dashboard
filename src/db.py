"""Database connection and utilities."""

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from src.config import settings

logger = logging.getLogger(__name__)


class Database:
    """Database connection pool manager."""

    def __init__(self):
        """Initialize connection pool."""
        self._pool = None

    def initialize(self):
        """Create the connection pool."""
        if self._pool is not None:
            return

        try:
            self._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=settings.database_url
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise

    def close(self):
        """Close all connections in the pool."""
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            logger.info("Database connection pool closed")

    @contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """
        Get a connection from the pool.

        Usage:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT ...")
                conn.commit()
        """
        if self._pool is None:
            self.initialize()

        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    @contextmanager
    def get_cursor(self, cursor_factory=RealDictCursor) -> Generator:
        """
        Get a cursor with automatic connection management.

        Usage:
            with db.get_cursor() as cur:
                cur.execute("SELECT ...")
                results = cur.fetchall()
        """
        with self.get_connection() as conn:
            cur = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()


# Global database instance
db = Database()


def execute_schema(schema_path: str = "db/schema.sql"):
    """
    Execute the schema SQL file to create/update database tables.

    Args:
        schema_path: Path to the schema SQL file
    """
    try:
        with open(schema_path, "r") as f:
            schema_sql = f.read()

        with db.get_cursor() as cur:
            cur.execute(schema_sql)

        logger.info(f"Schema executed successfully from {schema_path}")
    except FileNotFoundError:
        logger.error(f"Schema file not found: {schema_path}")
        raise
    except Exception as e:
        logger.error(f"Failed to execute schema: {e}")
        raise
