"""Guard: every mapped model must have a migration that creates its table.

Why this test exists
--------------------
``audit_logs`` shipped with a model in ``src/common/audit.py`` and **no**
Alembic migration. Every ``record_audit()`` call then raised
``OperationalError: no such table: audit_logs`` on a database created by
``alembic upgrade head`` — yet the suite stayed green, because ``conftest.py``
builds its schema with ``Base.metadata.create_all()`` instead of running
migrations, and no CI job ever executed one.

This closes that class of bug permanently: it runs the real migration chain
against a scratch database and compares the result with ``Base.metadata``. A
model added without a migration now fails the unit-test job immediately, with a
message naming the missing table.

The comparison is bidirectional on purpose. A table a migration creates that no
model declares is usually a stale migration left behind after a rename, which is
just as confusing to debug months later.

Runs in the unit-test job: SQLite only, no MySQL, no network, well under a
second. That matters — a guard that needs infrastructure gets skipped locally
and stops guarding anything.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect

from src.common.audit import AuditLog
from src.data.model_discovery import discover_mapped_tables

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_DIR = _REPO_ROOT / "src" / "data" / "migration"
_ENV_PY = _MIGRATION_DIR / "env.py"

# Tables that legitimately exist in a database but are not application models.
_IGNORED_TABLES = frozenset({"alembic_version"})


def _alembic_config(url: str) -> Config:
    """Build an Alembic config that targets a scratch database.

    The URL is passed through ``cmd_opts.x`` rather than by mutating process
    environment variables. Two reasons: ``env.py`` reads it via
    ``context.get_x_argument()``, which in turn reads ``config.cmd_opts.x``;
    and setting ``APP_DB_*`` env vars would fight the ``get_settings()`` cache
    that ``conftest.py`` deliberately clears around every test.
    """
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_MIGRATION_DIR))
    # `Namespace` mirrors what the `alembic` CLI puts on cmd_opts, so env.py
    # behaves identically under pytest and on the command line.
    config.cmd_opts = Namespace(x=[f"url={url}"])  # type: ignore[assignment]
    return config


def _scratch_url(tmp_path: Path, name: str) -> str:
    """A throwaway SQLite URL inside pytest's tmp dir."""
    return f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}"


def _migrated_tables(url: str) -> set[str]:
    """Run the full migration chain against `url` and return its tables."""
    command.upgrade(_alembic_config(url), "head")
    engine: Engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - _IGNORED_TABLES
    finally:
        engine.dispose()


def _declared_tables() -> set[str]:
    """Tables declared by every mapped model under ``src/``.

    Discovered by walking the filesystem (see ``src.data.model_discovery``), not
    by an import list maintained in this file. The previous version kept such a
    list and missed ``reservations``, so this guard passed while the table had no
    migration. ``env.py`` now calls the same function, so the two cannot drift.
    """
    return discover_mapped_tables() - _IGNORED_TABLES


def _env_py_calls_import_all_models() -> bool:
    """Does ``env.py`` actually call ``import_all_models()``?

    Read from source rather than imported: ``env.py`` accesses ``context.config``
    at module level, which only exists while Alembic is running, so importing it
    from a test raises AttributeError. A whole-line match is used so a mention in
    a comment cannot satisfy the check.
    """
    for line in _ENV_PY.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped == "import_all_models()":
            return True
    return False


class TestMigrationCompleteness:
    """The migration chain must produce exactly the schema the models declare."""

    def test_every_model_table_is_created_by_a_migration(self, tmp_path: Path) -> None:
        """A model with no migration must fail here, naming the missing table."""
        missing = sorted(
            _declared_tables() - _migrated_tables(_scratch_url(tmp_path, "completeness"))
        )
        assert not missing, (
            f"Tables declared by a mapped model but created by no migration: "
            f"{missing}. A database built with `alembic upgrade head` will raise "
            f"'no such table' at runtime while unit tests still pass, because "
            f"conftest.py uses Base.metadata.create_all(). Add a migration under "
            f"src/data/migration/versions/. No import list needs updating — "
            f"models are discovered automatically by src/data/model_discovery.py."
        )

    def test_no_orphan_tables_from_migrations(self, tmp_path: Path) -> None:
        """Migrations must not leave tables that no model declares."""
        orphans = sorted(_migrated_tables(_scratch_url(tmp_path, "orphans")) - _declared_tables())
        assert not orphans, (
            f"Tables created by a migration but declared by no mapped model: "
            f"{orphans}. Either the model no longer inherits from "
            f"src.data.database.Base, or the migration is stale and should be "
            f"replaced by a downgrade. Models are discovered automatically, so "
            f"there is no import list to update."
        )

    def test_audit_logs_specifically_is_migrated(self, tmp_path: Path) -> None:
        """Regression test for the bug this module exists to prevent."""
        migrated = _migrated_tables(_scratch_url(tmp_path, "audit_regression"))
        assert AuditLog.__tablename__ in migrated, (
            f"'{AuditLog.__tablename__}' has no migration. Audit logging is "
            f"required by Objective (f) and every record_audit() call fails "
            f"without this table."
        )


class TestMigrationChain:
    """Structural invariants of the revision chain."""

    def test_single_head(self) -> None:
        """Two heads means two people branched migrations and never merged.

        Alembic refuses to ``upgrade head`` with multiple heads, so this fails
        loudly here rather than at deploy time.
        """
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_MIGRATION_DIR))
        heads = ScriptDirectory.from_config(config).get_heads()
        assert len(heads) == 1, (
            f"Expected exactly one migration head, found {heads}. Reconcile the "
            f"branches with `alembic merge`."
        )

    def test_migration_env_uses_automatic_model_discovery(self) -> None:
        """``env.py`` must import every model automatically, not via a list.

        Autogenerate diffs ``target_metadata`` against the live database. A model
        that is not imported is absent from that metadata, so the next
        ``alembic revision --autogenerate`` emits a migration that **drops** its
        table. The old design kept a hand-written module tuple here and missed
        two models in six days. This test fails if ``env.py`` stops calling
        ``import_all_models()``, so the automatic path cannot be silently
        reverted to a list someone forgets to update.
        """
        assert _env_py_calls_import_all_models(), (
            "src/data/migration/env.py no longer calls import_all_models() on its "
            "own line. Models would once again depend on a hand-maintained import "
            "list, which is exactly how audit_logs and reservations shipped with no "
            "migration. Restore the call to src.data.model_discovery.import_all_models()."
        )

    def test_every_mapped_table_is_discovered(self, tmp_path: Path) -> None:
        """The known tables must all appear in discovery.

        A cheap tripwire: if discovery ever silently returns an empty or partial
        set (for example the walk starts excluding too much), the completeness
        test above would pass vacuously because declared ⊆ migrated becomes
        trivially true. Asserting the concrete expected tables are present keeps
        the guard honest.
        """
        declared = _declared_tables()
        expected = {
            "audit_logs",
            "reservations",
            "reviews",
            "review_moderation",
            "dish_rating_stats",
        }
        absent = sorted(expected - declared)
        assert not absent, (
            f"Model discovery did not find these expected tables: {absent}. "
            f"Discovery walks src/ automatically; a missing table here means a "
            f"model stopped inheriting from src.data.database.Base, or the walk "
            f"is excluding its module. Found: {sorted(declared)}"
        )

    @pytest.mark.parametrize("label", ["upgrade", "downgrade"])
    def test_migrations_are_reversible(self, tmp_path: Path, label: str) -> None:
        """The chain must survive a full up / down-to-base / up cycle.

        A downgrade that fails leaves a deployment unable to roll back, which is
        precisely when rollback matters. Verified by running the cycle rather
        than by reading the code. ``label`` only names the parametrised case.
        """
        assert label in {"upgrade", "downgrade"}
        url = _scratch_url(tmp_path, f"reversible_{label}")

        command.upgrade(_alembic_config(url), "head")
        command.downgrade(_alembic_config(url), "base")

        # After a full downgrade nothing application-owned should remain.
        engine = create_engine(url)
        try:
            emptied = set(inspect(engine).get_table_names()) - _IGNORED_TABLES
        finally:
            engine.dispose()
        assert not emptied, f"downgrade to base left tables behind: {sorted(emptied)}"

        command.upgrade(_alembic_config(url), "head")
        assert _migrated_tables(url) == _declared_tables()
