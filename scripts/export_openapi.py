"""Export the OpenAPI schema to a JSON file for the documentation deliverable.

Objective (f) requires a documented REST API. FastAPI generates the schema at
runtime, but the production deployment deliberately disables `/openapi.json`
(see src/presentation/api/main.py), and the technical report needs a stable
artefact to reference. This script produces it.

Usage, from the repository root:

    python scripts/export_openapi.py
    python scripts/export_openapi.py --output docs/api/openapi.json

The output is committed to `docs/api/` so a reviewer can read the contract
without running the application.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running as a plain script (`python scripts/export_openapi.py`) without
# installing the project first: put the repository root on sys.path.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "api" / "openapi.json"


def build_schema() -> dict[str, Any]:
    """Import the app and return its OpenAPI schema dict.

    Imported here rather than at module level so that `--help` works even when
    dependencies are missing, and so a broken module produces a clear error
    pointing at the application rather than at this script.
    """
    # Non-production so that openapi_url is not disabled — a production-mode app
    # returns None for the schema, and this script would write an empty file.
    from src.common.config import Settings
    from src.presentation.api.main import create_app

    app = create_app(Settings(environment="development"))
    schema = app.openapi()
    if not schema:
        msg = "Application produced an empty OpenAPI schema"
        raise RuntimeError(msg)
    return schema


def summarise(schema: dict[str, Any]) -> str:
    """Build a one-screen summary so CI output shows what was exported."""
    paths = schema.get("paths", {})
    total_operations = sum(
        1
        for methods in paths.values()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    )
    by_method: dict[str, int] = {}
    for methods in paths.values():
        for method in methods:
            if method in {"get", "post", "put", "patch", "delete"}:
                by_method[method] = by_method.get(method, 0) + 1
    breakdown = ", ".join(f"{m.upper()} {n}" for m, n in sorted(by_method.items()))
    return f"{len(paths)} path(s), {total_operations} operation(s)" + (
        f" — {breakdown}" if breakdown else ""
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the FastAPI OpenAPI schema to JSON.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination file (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 for a compact single-line file.",
    )
    args = parser.parse_args(argv)

    try:
        schema = build_schema()
    except Exception as exc:  # report any import/build failure clearly
        print(f"error: could not build the OpenAPI schema: {exc}", file=sys.stderr)
        print(
            "hint: are the dependencies installed? try `pip install -r requirements.txt`",
            file=sys.stderr,
        )
        return 1

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    indent = args.indent if args.indent > 0 else None
    # ensure_ascii=False keeps Chinese descriptions readable in the committed
    # file instead of escaping them to \uXXXX sequences.
    payload = json.dumps(schema, indent=indent, ensure_ascii=False, sort_keys=True)
    output_path.write_text(payload + "\n", encoding="utf-8")

    print(f"Wrote {output_path}")
    print(f"Schema: {summarise(schema)}")
    print(f"OpenAPI version: {schema.get('openapi', 'unknown')}")
    print(f"API title: {schema.get('info', {}).get('title', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
