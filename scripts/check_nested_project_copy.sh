#!/usr/bin/env bash
# Block a second copy of the project being uploaded into the repository root.
#
# Why this check exists
# ---------------------
# GitHub's web UI lets a contributor drag a whole folder onto the page. That
# creates a branch containing a *nested copy of the entire project* under a new
# root directory, instead of committing files into the existing tree. PR #24 did
# exactly this: it added 82 files under
#   bmis-group4-restaurant-system-upload-20261107/
# including its own src/, tests/, docs/, alembic.ini, pyproject.toml,
# requirements.txt, Dockerfile and a second copy of openapi.json.
#
# The damage is not cosmetic:
#
#   * The real code tree never receives the work. `git grep -i loyalty src`
#     returned nothing after PR #24 merged — the loyalty module existed only
#     inside the nested copy, so main.py never imported it and no endpoint,
#     migration or test ran.
#   * Every CI job stays green. Nothing outside the real tree is imported,
#     collected or built, so a 20,000-line drop of dead files passes all eight
#     jobs and merges behind a required-status-check that reported success.
#   * Revision identifiers collide. The nested copy carried
#     0004_add_loyalty_tables.py while the real tree already had
#     0004_add_membership_auth.py. Lifting the file out later produces an
#     Alembic "multiple heads" failure, so the copy cannot simply be moved in.
#   * The repository grows permanently. Those files stay in every future clone
#     even after the directory is deleted.
#
# This is the same class of defect as the empty-source-file guard in the hygiene
# job: a green pipeline that proves nothing about whether the delivered feature
# runs. The fix is to fail the build on shape, before review has to notice.
#
# How it decides
# --------------
# A tracked path can only be part of a nested copy if it sits in a subdirectory,
# so root-level files are skipped first. A subdirectory is then a nested project
# copy when it contains a *project marker* — a file only the project root is
# supposed to have (alembic.ini, pyproject.toml, requirements.txt, package.json,
# Dockerfile, docker-compose.yml, README.md, CONTRIBUTING.md), or when it
# contains both a src/ and a tests/ tree.
#
# Markers alone would be too broad: frontend/package.json is legitimate.
# Subdirectories alone would be too broad: docs/ and deploy/ are legitimate.
# Requiring a marker outside the project's own top-level directories describes
# only a second copy of this project.
#
# Deliberately NOT flagged
# ------------------------
# Loose files sitting directly in the repository root, such as schema.sql,
# schema.sql.txt, version and uk_member8_member_no. Those are a real hygiene
# problem, but a stray file is not a nested project, and where each one belongs
# is its owner's call rather than something to block every PR on. They are
# reported as a non-blocking warning at the end of this script instead.

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

# ---------------------------------------------------------------------------
# Registered debt: nested copies already on main when this guard was added.
#
# PR #24 merged its copy before the guard existed, and that directory is
# currently the ONLY copy of the loyalty module — deleting it now would destroy
# a teammate's work, so it stays until the module is moved into the real tree.
#
# Entries here are warned about on every run rather than failed, so the guard
# never turns every unrelated PR red because of pre-existing debt. An entry must
# be removed as soon as its directory is gone: this list is the tracking
# mechanism, not a permanent exemption. The step below fails if a registered
# entry no longer exists, so a stale entry cannot linger unnoticed — the same
# pattern as _COMMON_TIER_DEVIATIONS in tests/unit/test_architecture.py.
#
# Format: "<directory>|<reason it is still here>|<condition for removing it>"
# ---------------------------------------------------------------------------
REGISTERED_DEBT=(
  "bmis-group4-restaurant-system-upload-20261107|Only remaining copy of the loyalty module (PR #24 uploaded it here)|Remove this entry once M4 has moved the loyalty files into src/ and deleted the directory"
)

# Top-level directories that belong to this project. A marker inside any of
# these is expected and must not be reported.
OWN_TOP_LEVEL='^(src|tests|docs|deploy|frontend|scripts|\.github)(/|$)'

# Files that identify a project root.
MARKERS='(^|/)(alembic\.ini|pyproject\.toml|requirements(-dev)?\.txt|requirements\.in|package\.json|Dockerfile|docker-compose\.ya?ml|README\.md|CONTRIBUTING\.md)$'

_is_registered() {
  local candidate="$1" entry dir
  for entry in "${REGISTERED_DEBT[@]}"; do
    dir="${entry%%|*}"
    [ "$dir" = "$candidate" ] && return 0
  done
  return 1
}

_debt_note() {
  local candidate="$1" entry dir rest
  for entry in "${REGISTERED_DEBT[@]}"; do
    dir="${entry%%|*}"
    if [ "$dir" = "$candidate" ]; then
      rest="${entry#*|}"
      echo "    why it is still here: ${rest%%|*}"
      echo "    remove the entry when: ${rest##*|}"
      return 0
    fi
  done
  return 1
}

echo "Scanning tracked files for a nested copy of the project..."

# Only paths inside a subdirectory can belong to a nested copy; root-level files
# are handled by the stray-file warning at the end.
SUSPECT_DIRS=$(git ls-files | grep / | grep -vE "$OWN_TOP_LEVEL" \
  | grep -E "$MARKERS" \
  | cut -d/ -f1 | sort -u || true)

FAILED=0
DEBT_FOUND=""

for dir in $SUSPECT_DIRS; do
  [ -d "$dir" ] || continue

  MARKER_FILES=$(git ls-files -- "$dir" | grep -E "$MARKERS" | sed "s|^$dir/||" | sort -u)
  MARKER_COUNT=$(printf '%s\n' "$MARKER_FILES" | grep -c . || true)
  TOTAL=$(git ls-files -- "$dir" | wc -l | tr -d ' ')
  HAS_SRC=$(git ls-files -- "$dir" | grep -cE "(^|/)src/" || true)
  HAS_TESTS=$(git ls-files -- "$dir" | grep -cE "(^|/)tests/" || true)

  if [ "$MARKER_COUNT" -lt 1 ] && { [ "$HAS_SRC" -lt 1 ] || [ "$HAS_TESTS" -lt 1 ]; }; then
    continue
  fi

  if _is_registered "$dir"; then
    echo "::warning::Registered nested copy still present: $dir/ ($TOTAL tracked files)"
    _debt_note "$dir"
    DEBT_FOUND="$DEBT_FOUND $dir"
    continue
  fi

  echo "::error::Nested copy of the project committed at: $dir/"
  echo "    tracked files: $TOTAL"
  echo "    project markers found:"
  printf '%s\n' "$MARKER_FILES" | sed 's/^/      /'
  FAILED=1
done

# A registered entry whose directory has been cleaned up must be deleted from
# the list above, otherwise the exemption outlives the debt it was granted for.
for entry in "${REGISTERED_DEBT[@]}"; do
  dir="${entry%%|*}"
  if [ ! -d "$dir" ]; then
    echo "::error::Stale entry in REGISTERED_DEBT: $dir/ no longer exists."
    echo "    Delete that line from scripts/check_nested_project_copy.sh so the"
    echo "    guard covers the directory again if someone re-adds it."
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "A whole second copy of the project was committed into the repository root."
  echo "This happens when files are dragged onto GitHub's web UI instead of being"
  echo "committed into the existing tree."
  echo ""
  echo "Why this cannot be merged as-is:"
  echo "  * Code inside the copy is never imported, collected or built, so the"
  echo "    delivered feature does not exist in the running application — while all"
  echo "    eight CI jobs still report success."
  echo "  * Alembic revision identifiers inside the copy collide with the real"
  echo "    migration chain, so the files cannot simply be moved in later."
  echo "  * The copy stays in every future clone forever, even after deletion."
  echo ""
  echo "How to fix it:"
  echo "  1. Branch from the CURRENT main: git checkout -b <branch> origin/main"
  echo "  2. Move your files into the real tree (models under src/data/schema/ or"
  echo "     src/application/<module>/, migrations under"
  echo "     src/data/migration/versions/ with down_revision pointing at the"
  echo "     current head, tests under tests/unit/ or tests/integration/)."
  echo "  3. Delete the nested directory entirely."
  echo "  4. Commit from a git client, not the web UI, and open a pull request."
  echo ""
  echo "See CONTRIBUTING.md. If your work only exists inside that nested copy,"
  echo "recover it first: git show <branch>:<path> > <real-path>."
  exit 1
fi

if [ -n "$DEBT_FOUND" ]; then
  echo ""
  echo "OK: no NEW nested copy. Registered debt still awaiting cleanup:$DEBT_FOUND"
else
  echo "OK: no nested copy of the project in the repository root."
fi

# ---------------------------------------------------------------------------
# Root-file allowlist (warning only, non-blocking)
#
# Loose files in the repository root are a hygiene problem but not a nested
# project, and blocking every PR on them would stall unrelated work while the
# owners sort out where each file belongs. Warn loudly instead: the output names
# the file and the directory it should be in, which is enough for a reviewer to
# ask for a move, and enough to stop a third copy from being added silently.
# ---------------------------------------------------------------------------
ALLOWED_ROOT_FILES='^(\.env\.example|\.gitattributes|\.gitignore|alembic\.ini|CONTRIBUTING\.md|INSTALL\.md|pyproject\.toml|README\.md|requirements-dev\.txt|requirements\.txt)$'

echo ""
echo "Checking for unexpected loose files in the repository root..."
STRAY=$(git ls-files | grep -v / | grep -vE "$ALLOWED_ROOT_FILES" || true)

if [ -n "$STRAY" ]; then
  echo "::warning::Unexpected loose file(s) in the repository root:"
  printf '%s\n' "$STRAY" | sed 's/^/    /'
  echo ""
  echo "    Root files should be limited to project configuration and top-level"
  echo "    documentation. Move anything else into the directory that owns it:"
  echo "      schema / DDL          -> src/data/migration/versions/ (Alembic chain)"
  echo "      notes, scratch SQL    -> delete; they are not code"
  echo "      testing documents     -> docs/testing/"
  echo "      design documents      -> docs/design/"
  echo ""
  echo "    Non-blocking: a stray file does not break the build, but it does mean"
  echo "    the schema has a second, unauthoritative source of truth."
else
  echo "OK: only expected configuration and documentation at the root."
fi
