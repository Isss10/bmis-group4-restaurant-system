"""Guards for how module routers are discovered and mounted.

These tests exist because of a real defect that every CI job passed:

`_register_module_routers` used to derive the base path from the module
directory name, so `reservation/` was mounted at `/api/v1/reservation` — while
the module table in `main.py`, ARCHITECTURE.md §2 and manual §4.2 all advertise
`/api/v1/reservations`. Nothing asserted the mounted prefix, so the three Vue
apps were guaranteed to 404 against a green pipeline. The same mapping also
pointed at `src/application/<module>/router.py`, which contradicts
ARCHITECTURE.md §3 ("Application ... Must NOT import `fastapi`").

A defect like this is invisible to unit tests that only exercise `/health`, and
invisible to Docker smoke tests that only curl `/health`. It is caught only by
asserting the mounted route table itself — which is what this file does.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, status
from fastapi.testclient import TestClient

from src.common.config import Settings
from src.presentation.api.main import _MODULE_ROUTERS, create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

# The frozen base paths. Sources, all of which must agree:
#   * `main.py` `_DESCRIPTION` module table
#   * ARCHITECTURE.md §2 (ASCII tier diagram) and §7 (module boundaries)
#   * manual §4.2 (REST naming) and §4.4 (cross-module interface table)
FROZEN_BASE_PATHS: dict[str, str] = {
    "reservation": "/api/v1/reservations",
    "ordering": "/api/v1/orders",
    "staff": "/api/v1/staff",
    "membership": "/api/v1/membership",
    "review": "/api/v1/reviews",
    "analytics": "/api/v1/analytics",
}

# ARCHITECTURE.md §3 says the common tier may import "nothing in `src/`", read
# as *nothing outside itself* — `src.common.config` importing `src.common.errors`
# is intra-package and fine. Reaching into another tier is not.
#
# One such import exists today, listed here explicitly:
#
#   src/common/audit.py -> src.data.database
#
# `AuditLog(Base)` needs SQLAlchemy's declarative Base, which lives in the data
# tier, so common depends upward on data while data depends downward on common.
# It is not a *runtime* cycle (audit -> database -> config stops there), but it
# is a layering violation, and it is pinned here rather than silently allowed so
# that the next one cannot slip in unnoticed.
#
# Fixing it properly means moving `AuditLog` into `src/data/schema/` — a boundary
# ARCHITECTURE.md §6 assigns to YUANYUAN XUE (the schema owner), and it changes
# which Alembic migration owns the table. That is a contract-review PR with the
# schema owner, not something to fold into this branch. Until then the deviation
# is visible and bounded.
_COMMON_TIER_DEVIATIONS: frozenset[str] = frozenset(
    {
        "src/common/audit.py -> src.data.database",
    }
)


class TestModuleRouterTable:
    def test_table_matches_the_frozen_base_paths(self) -> None:
        """The mapping is contract, not convention — pin every entry.

        Renaming a base path is a breaking change for three frontends, so it
        must be a deliberate edit to both this test and the documents it cites.
        """
        assert {name: path for name, (_, path) in _MODULE_ROUTERS.items()} == FROZEN_BASE_PATHS

    def test_routers_live_in_the_presentation_tier(self) -> None:
        """ARCHITECTURE.md §3 forbids `fastapi` in the application tier.

        A router is HTTP surface, so it belongs in `presentation`. Pointing the
        loader at `src/application/.../router.py` would force every module owner
        to either break the dependency rule or write a router that never mounts.
        """
        for name, (module_path, _) in _MODULE_ROUTERS.items():
            assert module_path == f"src.presentation.api.routers.{name}"

    def test_every_base_path_is_versioned(self) -> None:
        for name, prefix in FROZEN_BASE_PATHS.items():
            assert prefix.startswith("/api/v1/"), f"{name} must be under the versioned prefix"
            assert prefix == prefix.rstrip("/"), f"{name} prefix must not end in a slash"
            # One level only: nested resources are declared inside the router.
            assert prefix.removeprefix("/api/v1/").count("/") == 0, name

    @pytest.mark.parametrize(
        ("module_name", "expected"),
        [
            # Directory names are singular; API paths are plural resource names
            # (manual §4.2). These three pairs are exactly where a derived
            # prefix goes wrong, so they are asserted individually.
            ("reservation", "/api/v1/reservations"),
            ("ordering", "/api/v1/orders"),
            ("review", "/api/v1/reviews"),
        ],
    )
    def test_plural_resource_paths_are_not_the_directory_name(
        self, module_name: str, expected: str
    ) -> None:
        assert _MODULE_ROUTERS[module_name][1] == expected
        assert not expected.endswith(f"/{module_name}")


class TestRouterMounting:
    """Exercise the loader with a stand-in router, since no module has one yet."""

    @pytest.fixture
    def probe_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/probe")
        async def probe() -> dict[str, str]:
            return {"mounted": "yes"}

        return router

    def _install(
        self, monkeypatch: pytest.MonkeyPatch, name: str, module: types.ModuleType
    ) -> None:
        monkeypatch.setitem(sys.modules, f"src.presentation.api.routers.{name}", module)

    def test_a_present_router_mounts_at_its_frozen_prefix(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings, probe_router: APIRouter
    ) -> None:
        fake = types.ModuleType("src.presentation.api.routers.reservation")
        fake.router = probe_router
        self._install(monkeypatch, "reservation", fake)

        with TestClient(create_app(settings)) as client:
            response = client.get(f"{FROZEN_BASE_PATHS['reservation']}/probe")
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {"mounted": "yes"}

    def test_the_singular_directory_name_is_not_a_route(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings, probe_router: APIRouter
    ) -> None:
        """Regression test for the derived-prefix defect.

        If the loader ever goes back to building the prefix from the module
        name, this starts returning 200 and the test fails — which is the point:
        the wrong path answering is as broken as no path answering.
        """
        fake = types.ModuleType("src.presentation.api.routers.reservation")
        fake.router = probe_router
        self._install(monkeypatch, "reservation", fake)

        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/reservation/probe").status_code == status.HTTP_404_NOT_FOUND

    def test_mounted_routes_are_tagged_with_the_module_name(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings, probe_router: APIRouter
    ) -> None:
        """Tags group the module in /docs, which is the Objective (f) deliverable.

        Asserted through the OpenAPI document rather than `app.routes`: the
        route collection's internal shape varies by Starlette version, while
        the generated document is the artefact that is actually delivered.
        """
        fake = types.ModuleType("src.presentation.api.routers.review")
        fake.router = probe_router
        self._install(monkeypatch, "review", fake)

        schema: Any = create_app(settings).openapi()
        path = f"{FROZEN_BASE_PATHS['review']}/probe"
        assert path in schema["paths"], sorted(schema["paths"])
        assert "review" in schema["paths"][path]["get"]["tags"]

    def test_a_missing_router_does_not_break_the_app(self, settings: Settings) -> None:
        """The whole point of the tolerance: an empty repo still serves /health."""
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == status.HTTP_200_OK

    def test_a_module_without_a_router_attribute_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        fake = types.ModuleType("src.presentation.api.routers.ordering")
        self._install(monkeypatch, "ordering", fake)

        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == status.HTTP_200_OK
            assert client.get("/api/v1/orders/probe").status_code == status.HTTP_404_NOT_FOUND

    def test_a_broken_router_does_not_sink_the_app(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """Docker health checks must not be held hostage by one module's typo."""
        fake = types.ModuleType("src.presentation.api.routers.analytics")
        fake.router = "this is not an APIRouter"  # type: ignore[attr-defined]
        self._install(monkeypatch, "analytics", fake)

        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/health").status_code == status.HTTP_200_OK


class TestTierDependencyRule:
    """ARCHITECTURE.md §3: dependencies point downward, never upward.

    Ruff and mypy do not enforce a layering rule, and the repository has no
    import-linter configured, so the rule is asserted here instead. Static
    parsing (rather than importing) means this also catches an import inside a
    function body that never executes in tests.
    """

    def _imported_roots(self, source: str, path: Path) -> set[str]:
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:  # pragma: no cover - a syntax error fails lint first
            return set()
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        return roots

    def test_application_tier_does_not_import_fastapi(self) -> None:
        offenders: list[str] = []
        for path in sorted((REPO_ROOT / "src" / "application").rglob("*.py")):
            if "fastapi" in self._imported_roots(path.read_text(encoding="utf-8"), path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, (
            "The application tier must not import fastapi (ARCHITECTURE.md §3). "
            "Raise ApiError from src/common/errors.py and let the router translate it: "
            f"{offenders}"
        )

    def test_data_tier_does_not_import_fastapi_or_presentation(self) -> None:
        offenders: list[str] = []
        for path in sorted((REPO_ROOT / "src" / "data").rglob("*.py")):
            roots = self._imported_roots(path.read_text(encoding="utf-8"), path)
            if "fastapi" in roots:
                offenders.append(f"{path.relative_to(REPO_ROOT)} (fastapi)")
        assert not offenders, f"The data tier must stay framework-free: {offenders}"

    def test_common_tier_imports_nothing_from_src(self) -> None:
        """`src/common/` is the leaf every tier depends on; it must not reach up.

        One known deviation is listed in ``_COMMON_TIER_DEVIATIONS`` below and
        is pinned rather than ignored: allowing the import silently would let
        the next one in unnoticed, and this pair is a genuine import cycle.
        """
        offenders: list[str] = []
        for path in sorted((REPO_ROOT / "src" / "common").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source, filename=str(path))):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    targets = [node.module]
                else:
                    continue
                for target in targets:
                    if not target.startswith("src.") or target.startswith("src.common"):
                        continue
                    entry = f"{path.relative_to(REPO_ROOT).as_posix()} -> {target}"
                    if entry not in _COMMON_TIER_DEVIATIONS:
                        offenders.append(entry)
        assert not offenders, (
            "src/common must not import from src (ARCHITECTURE.md §3: Common may import "
            f"'nothing in src/'). New violations found: {offenders}. If one is genuinely "
            "required, add it to _COMMON_TIER_DEVIATIONS with the coordinating PR "
            "referenced — do not weaken the check."
        )

    def test_deviation_list_has_no_stale_entries(self) -> None:
        """A deviation that stops being real must be deleted, not left to rot.

        Without this, the allowlist grows into a permanent exemption that hides
        new violations — the exact failure mode an allowlist introduces.
        """
        present = set()
        for path in sorted((REPO_ROOT / "src" / "common").rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    targets = [node.module]
                present.update(f"{rel} -> {t}" for t in targets if t.startswith("src."))
        stale = sorted(_COMMON_TIER_DEVIATIONS - present)
        assert not stale, f"Remove these resolved deviations from the allowlist: {stale}"


class TestNoSourceFileIsAnEmptyPlaceholder:
    """An empty `models.py` plus no test importing it is a silent green CI.

    PR #3 shipped `src/application/reservation/models.py` and `repository.py`
    as zero-byte files while `service.py` did `from models import ...`; the
    module raised ModuleNotFoundError on import and every job still passed,
    because nothing imported it. The CI hygiene job now fails the build on this;
    this test is the same rule enforced locally, where the author sees it first.

    `__init__.py` and `.gitkeep` are legitimately empty.
    """

    def test_no_tracked_python_module_is_empty(self) -> None:
        empty: list[str] = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            if path.name == "__init__.py":
                continue
            if len(path.read_bytes().strip()) == 0:
                empty.append(str(path.relative_to(REPO_ROOT)))
        assert not empty, (
            "These source files are empty placeholders, which import as nothing "
            f"and pass CI silently: {empty}. Delete them or fill them in."
        )

    def test_presentation_routers_package_is_importable(self) -> None:
        """The package the loader imports from must actually exist."""
        assert (REPO_ROOT / "src" / "presentation" / "api" / "routers" / "__init__.py").exists()
        assert isinstance(sys.modules.get("src.presentation.api.routers"), types.ModuleType)


def test_openapi_still_generates_with_no_modules_present(settings: Settings) -> None:
    """`scripts/export_openapi.py` is the Objective (f) evidence; it must not crash."""
    app = create_app(settings)
    schema: Any = app.openapi()
    assert schema["paths"].keys() >= {"/", "/api/v1/health", "/api/v1/auth/me"}
