"""Regression coverage for MySQL-safe loyalty migration rollback."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


def test_loyalty_downgrade_drops_child_tables_without_dropping_fk_indexes() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src/data/migration/versions/0005_add_loyalty_tables.py"
    )
    spec = importlib.util.spec_from_file_location("loyalty_migration_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dropped_tables: list[str] = []
    with (
        patch.object(module.op, "drop_table", side_effect=dropped_tables.append),
        patch.object(
            module.op,
            "drop_index",
            side_effect=AssertionError("MySQL FK-backed indexes must not be dropped first"),
        ),
    ):
        module.downgrade()

    assert dropped_tables == [
        "user_coupons",
        "coupons",
        "points_allocations",
        "points_ledger",
        "loyalty_order_events",
        "membership_tiers",
    ]
