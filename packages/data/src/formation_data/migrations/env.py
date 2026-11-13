"""Alembic environment for formation_data.

Run through `formation_data.migrate` (the `formation-data db ...` commands), which
passes an open connection in `config.attributes["connection"]` so a whole upgrade,
adoption included, is one transaction. Without one it connects to DATABASE_URL.
"""

from __future__ import annotations

from alembic import context

from formation_data import schema
from formation_data.db import _database_url, get_engine
from formation_data.migrate import include_object

config = context.config


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=schema.metadata,
        compare_type=True,
        include_object=include_object,
        **kwargs,
    )


def run_offline() -> None:
    """Emit SQL instead of running it (`alembic upgrade --sql`)."""
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    with get_engine().begin() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
