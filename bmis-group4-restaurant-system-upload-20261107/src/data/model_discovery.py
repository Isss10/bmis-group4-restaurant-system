"""Automatic discovery of every mapped model in the codebase.

Why this module exists
----------------------
Alembic's autogenerate and the migration-completeness guard both need the full
``Base.metadata``. For a long time each of them maintained its **own
hand-written import list** — ``_IMPORT_MODEL_MODULES`` in
``src/data/migration/env.py`` and the import block at the top of
``tests/unit/test_migration_completeness.py``.

That design failed twice, six days apart:

* ``audit_logs`` (model in ``src/common/audit.py``) was missing from both lists,
  so it had no migration and ``record_audit()`` raised ``no such table`` on any
  database built with ``alembic upgrade head``.
* ``reservations`` (model in ``src/application/reservation/models.py``) was
  missing from both lists too, so PR #3 merged a model with no migration. The
  guard test existed by then and still passed — it could not see a table that was
  never imported.

A hand-maintained list is the bug. This module replaces both lists with a
filesystem walk, so **adding a model requires no edit anywhere**. One mechanism,
used by both callers, which means they can no longer disagree.

Contract for model authors
--------------------------
Declare your model in any module under ``src/`` (except ``src/data/migration/``,
which holds generated code) and inherit from ``src.data.database.Base``. It will
be picked up automatically by migrations, by autogenerate and by the guard test.

Import failures are fatal, not skipped. A module that raises on import is a real
bug, and silently ignoring it would reproduce exactly the invisibility this
module exists to remove. The one legitimate exception — ``src/data/migration/`` —
is excluded by path, not by catching an error: ``env.py`` calls
``context.config`` at module level and only works while Alembic is running.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from src.data.database import Base

logger = logging.getLogger(__name__)

# src/data/model_discovery.py -> parents[1] is src/, its parent is the repo root.
_SRC_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SRC_ROOT.parent

# Directory names skipped entirely. `migration` holds Alembic's env.py (not
# importable outside a migration run) and generated revision files.
_SKIPPED_DIR_NAMES = frozenset({"migration"})

# __pycache__ and similar; defensive, since rglob would otherwise match nothing
# importable in them anyway.
_SKIPPED_FILE_NAMES = frozenset({"__init__.py"})


def _iter_module_names() -> list[str]:
    """Every importable module under ``src/``, as a dotted name, sorted.

    Sorted so that failures are reported deterministically and so that the
    import order does not depend on filesystem enumeration order — a model that
    only imports cleanly after another one would otherwise pass or fail based on
    the operating system.
    """
    names: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        parts = path.relative_to(_SRC_ROOT).parts
        if _SKIPPED_DIR_NAMES.intersection(parts):
            continue
        if path.name in _SKIPPED_FILE_NAMES:
            continue
        dotted = ".".join(("src", *parts[:-1], path.stem))
        names.append(dotted)
    return sorted(set(names))


def import_all_models() -> list[str]:
    """Import every module under ``src/`` and return the ones imported.

    Raises
    ------
    RuntimeError
        If any module fails to import. The message lists every failure with its
        exception type, because the usual cause is a genuine bug in a model
        module and hiding it would let a table go missing again.
    """
    imported: list[str] = []
    failures: list[str] = []

    for module_name in _iter_module_names():
        try:
            importlib.import_module(module_name)
            imported.append(module_name)
        except Exception as exc:  # reported below, never swallowed
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")

    if failures:
        joined = "\n  ".join(failures)
        msg = (
            f"{len(failures)} module(s) under src/ could not be imported, so "
            f"Base.metadata is incomplete and migrations may miss tables:\n  "
            f"{joined}\n"
            f"Fix the module. Do not add it to a skip list: a model that cannot "
            f"be imported is invisible to Alembic autogenerate, which then emits "
            f"a migration that DROPS its table."
        )
        raise RuntimeError(msg)

    logger.debug("Imported %d modules for model discovery", len(imported))
    return imported


def discover_mapped_tables() -> set[str]:
    """Table names declared by every mapped model found under ``src/``.

    This is the authoritative answer to "what schema should the database have?".
    Both the migration environment and the completeness guard call it, so the
    two can never disagree.
    """
    import_all_models()
    return set(Base.metadata.tables)
