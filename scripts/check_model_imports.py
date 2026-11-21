"""Fail the build when any module under ``src/`` cannot be imported.

Why this step exists
--------------------
``src/data/model_discovery.py`` walks the filesystem and imports every module
under ``src/`` so that Alembic's autogenerate and the migration-completeness
guard both see the full ``Base.metadata``. Its contract is explicit: **import
failures are fatal, not skipped**, because a model that cannot be imported is
invisible to autogenerate, which then emits a migration that DROPS its table.

That contract is already enforced indirectly — ``tests/unit/
test_migration_completeness.py`` calls ``discover_mapped_tables()``, the
integration job runs ``alembic upgrade head`` (whose ``env.py`` calls
``import_all_models()``), and the Docker job boots a container that runs the
same migration. A broken model file therefore does turn CI red today.

The problem is *attribution*. When it happens, three separate jobs fail with
three unrelated-looking messages: a migration-completeness test error, an
Alembic failure, and a container that never becomes healthy. Nobody reading
that output learns the actual cause in under a minute — "your new file does not
import". On 19 Nov 2026 a branch added ``src/models/reservation.py`` containing
``from .base import Base`` while ``src/models/base.py`` did not exist. Merging
it would have raised ``ModuleNotFoundError`` inside model discovery and taken
down the pipeline for all ten members, exactly as the pytest-asyncio
configuration defect did on 4 Nov.

This script reports that cause directly, in seconds, naming the file and the
exception. It deliberately **reuses ``_iter_module_names()``** rather than
walking the tree itself: a second, independent list of modules is precisely the
bug ``model_discovery.py`` was written to remove (it replaced two hand-written
import lists that had drifted apart and missed ``audit_logs`` and
``reservations``). One source of truth, even for the guard that checks it.

Usage
-----
    python scripts/check_model_imports.py

Requires the same environment variables the test jobs set
(``APP_ENVIRONMENT``, ``APP_JWT_SECRET_KEY``, ``APP_DB_NAME``), because
importing ``src.data.database`` pulls in ``src.common.config``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Allow `python scripts/check_model_imports.py` from a clean checkout without
# PYTHONPATH being set, which is how a teammate will run it locally.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _module_to_file(dotted: str) -> Path:
    """``src.models.reservation`` -> ``<repo>/src/models/reservation.py``."""
    return REPO_ROOT.joinpath(*dotted.split(".")).with_suffix(".py")


def main() -> int:
    from src.data.database import Base
    from src.data.model_discovery import _iter_module_names

    names = _iter_module_names()
    imported: list[str] = []
    failures: list[tuple[str, BaseException]] = []

    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - every failure must be reported
            failures.append((name, exc))
        else:
            imported.append(name)

    if failures:
        print(f"FAIL: {len(failures)} of {len(names)} module(s) under src/ do not import.\n")
        for name, exc in failures:
            path = _module_to_file(name)
            shown = path.relative_to(REPO_ROOT).as_posix()
            exists = "" if path.exists() else "  (file not found at this path)"
            print(f"  {name}\n    file: {shown}{exists}\n    {type(exc).__name__}: {exc}\n")
        print(
            "Why this blocks the merge: src/data/model_discovery.py imports every\n"
            "module under src/ and treats an import failure as fatal, so this file\n"
            "would break the migration chain, the integration job and the Docker\n"
            "container at the same time. Fix the module — do not add it to a skip\n"
            "list. A model that cannot be imported is invisible to Alembic\n"
            "autogenerate, which then emits a migration that DROPS its table.\n"
            "\n"
            "Reproduce locally:\n"
            "  APP_ENVIRONMENT=testing APP_JWT_SECRET_KEY=local-only \\\n"
            "  APP_DB_NAME=restaurant_test PYTHONPATH=. \\\n"
            "  python scripts/check_model_imports.py"
        )
        return 1

    tables = sorted(Base.metadata.tables)
    print(f"OK: imported {len(imported)} module(s) under src/.")
    print(f"Mapped tables ({len(tables)}): {', '.join(tables)}")
    print(
        "\nEvery module imports, so Base.metadata is complete and Alembic\n"
        "autogenerate cannot silently miss a table."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
