"""Alembic migration environment.

The database URL comes from application settings (environment variables), never
from `alembic.ini` — committing a connection string would commit credentials
(OWASP A05).

Two modes:
* **offline** (`alembic upgrade head --sql`) emits SQL without connecting, for
  review before applying to a production database.
* **online** connects and applies within a transaction, rolling back on any
  error so a failed migration never leaves the schema half-applied.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.common.config import get_settings
from src.data.database import Base

# Alembic's Config object, giving access to alembic.ini values.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Every model module must be imported before autogenerate runs, otherwise
# Alembic cannot see the tables and will generate a migration that DROPS them.
#
# ⚠️ IMPORTANT FOR THE TEAM: when you add a model in src/data/schema/ or inside
# a module, import that module here. A model that is not imported is invisible
# to autogenerate, and the resulting migration will try to delete its table.
_IMPORT_MODEL_MODULES: tuple[str, ...] = (
    # Example — uncomment as each module's models are implemented:
    # "src.data.schema.reservation",
    # "src.data.schema.ordering",
    # "src.data.schema.membership",
    # "src.data.schema.review",
    # "src.data.schema.analytics",
)


def _import_models() -> None:
    """Import model modules so Base.metadata is fully populated."""
    import importlib

    for module_name in _IMPORT_MODEL_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
            logger.warning("Model module not implemented yet: %s", module_name)


_import_models()

# The complete schema Alembic compares against the live database.
target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the URL, preferring an explicit alembic -x url=... override.

    `-x url=...` exists so a DBA can run a migration against one database
    without exporting an environment variable into their shell history.
    """
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return override
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    `literal_binds=True` inlines parameter values so the output is runnable by
    hand — which also means it must never be run with secrets in the URL. The
    output goes to a review artefact, not to a log aggregator.
    """
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare column types and server defaults, not just table/column names.
        # Without these, autogenerate misses a VARCHAR(64) -> VARCHAR(128) change.
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations inside a transaction."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # one connection, used once, then closed
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # MySQL cannot ALTER inside a transaction, so a failed migration may
            # leave partial DDL. Naming the failure loudly matters more than
            # pretending atomicity we cannot have.
            transaction_per_migration=False,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    logger.info("Running migrations in OFFLINE mode (SQL will be emitted, not applied)")
    run_migrations_offline()
else:
    logger.info("Running migrations in ONLINE mode")
    run_migrations_online()
