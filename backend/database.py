"""
SQLAlchemy Database Engine and Session Factory
==============================================

Sets up the SQLAlchemy connection pool and provides the ``get_db`` FastAPI
dependency that yields a per-request database session.

Connection string is assembled from environment variables so that the same
code works both inside Docker (where ``POSTGRES_HOST=postgres``) and on a
developer's workstation (where ``POSTGRES_HOST=localhost``).

Environment variables:
    POSTGRES_USER     – database user (default: ``weather_user``)
    POSTGRES_PASSWORD – database password (default: ``weather_pass``)
    POSTGRES_HOST     – hostname / service name (default: ``postgres``)
    POSTGRES_PORT     – TCP port (default: ``5432``)
    POSTGRES_DB       – database name (default: ``weather_db``)

Exports:
    engine       – SQLAlchemy ``Engine`` instance (used by ORM and Alembic).
    SessionLocal – ``sessionmaker`` factory bound to the engine.
    Base         – Declarative base class; imported by all ORM model modules.
    get_db       – FastAPI dependency that yields a session and ensures cleanup.

Author: <project maintainer>
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Assemble the PostgreSQL DSN from environment variables.
# pool_pre_ping=True makes SQLAlchemy test the connection before using it from
# the pool, which recovers gracefully from server-side connection timeouts.
DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('POSTGRES_USER', 'weather_user')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'weather_pass')}@"
    f"{os.getenv('POSTGRES_HOST', 'postgres')}:"
    f"{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'weather_db')}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# autocommit=False and autoflush=False are the standard FastAPI settings:
# each request gets an explicit transaction that is committed only on success.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a scoped SQLAlchemy session.

    Opens a new ``SessionLocal`` session for the duration of one HTTP request
    and closes it unconditionally in the ``finally`` block, even if the route
    handler raises an exception. Transactions are committed by the route
    handler; uncommitted changes are automatically rolled back when the session
    is closed.

    Yields:
        Session: An open SQLAlchemy ORM session bound to the configured
            PostgreSQL engine.

    Example::

        @app.get("/example")
        def example_route(db: Session = Depends(get_db)):
            return db.query(MyModel).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
