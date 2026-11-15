# Installation & Running Guide

**JC2001 BMIS Group 4 — Restaurant Reservation and Food-Ordering System**

This document gets the proof-of-concept running from a clean machine. Two paths
are provided: **Path A (Docker, recommended)** brings up the database and the API
in one command; **Path B (manual)** runs each component directly and is what you
need if you want to run the test suite or develop.

> **Status note (read before you trust every step).** The commands below are
> transcribed from the committed `deploy/docker/` files, `.env.example`,
> `README.md` and the CI workflow, so they match the repository as it stands.
> An **end-to-end run on a clean, never-developed-on machine has not yet been
> performed** — that is a tracked gap before the 14 Dec submission (the marking
> rubric rewards reproducibility, and `docker compose up` on a fresh clone is the
> check). If a step fails for you, the "Troubleshooting" section at the end
> covers the failures we anticipate.

**Prerequisites**

| Tool | Version | Needed for |
|---|---|---|
| Docker + Docker Compose | Docker 24+, Compose v2 | Path A |
| Python | **3.11** (the project requires `>=3.11,<3.13`) | Path B, tests |
| Node.js + npm | Node 20+ | the two frontends |
| Git | any recent | cloning |

Python **3.11** specifically: the project pins `requires-python = ">=3.11,<3.13"`,
and CI runs 3.11. 3.13/3.14 will fail to collect tests because a dependency
emits a deprecation warning that this project's `filterwarnings = ["error"]`
turns into a hard error (see Troubleshooting).

---

## Path A — Docker (recommended)

One command builds the API image and starts MySQL 8.0 beside it:

```bash
# from the repository root
docker compose -f deploy/docker/docker-compose.yml up --build
```

What this does:

1. Builds the API from `deploy/docker/Dockerfile` (multi-stage, runs as a
   non-root user).
2. Starts MySQL 8.0 with InnoDB, `utf8mb4`, and **READ COMMITTED** isolation set
   at the server level (the concurrency design depends on these).
3. Waits for MySQL to pass its healthcheck, then the API container runs
   `alembic upgrade head` (creating every table) followed by `uvicorn`.

**Endpoints once it is up:**

| URL | What |
|---|---|
| http://localhost:8000/health | Liveness probe — should return HTTP 200 |
| http://localhost:8000/docs | Interactive API documentation (Swagger UI) |
| http://localhost:8000/api/v1 | The API base path |
| localhost:3307 | MySQL (host port **3307**, mapped to the container's 3306, so it does not clash with a local MySQL) |

**Verify it is actually healthy:**

```bash
curl http://localhost:8000/health
# expect HTTP 200 with the service envelope {"code":0,"message":"ok",...}
```

**Stop the stack:**

```bash
docker compose -f deploy/docker/docker-compose.yml down       # keep the database
docker compose -f deploy/docker/docker-compose.yml down -v    # ALSO delete the database volume
```

**Optional database browser** (phpMyAdmin on http://localhost:8081):

```bash
docker compose -f deploy/docker/docker-compose.yml --profile tools up
```

> The compose file ships **development credentials only** (e.g.
> `local-dev-password`). They are placeholders for a throwaway local container and
> must never be reused in a real deployment.

---

## Path B — Manual (for development and testing)

### B1. Backend

```bash
# 1. Clone and enter the repository
git clone git@github.com:Isss10/bmis-group4-restaurant-system.git
cd bmis-group4-restaurant-system

# 2. Create a Python 3.11 virtual environment
python3.11 -m venv .venv
#    Windows PowerShell:  .\.venv\Scripts\Activate.ps1
#    macOS / Linux:       source .venv/bin/activate

# 3. Install dependencies (runtime + development/test tooling)
pip install -r requirements.txt -r requirements-dev.txt
```

> **Windows: if `pip install` appears to hang**, direct access to `pypi.org` can
> be very slow on some networks. Use a mirror:
> `pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt -r requirements-dev.txt`

```bash
# 4. Create your environment file and set a real JWT secret
#    Windows PowerShell:  Copy-Item .env.example .env
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
#    paste the printed value into APP_JWT_SECRET_KEY in .env (it must be >= 32 chars)
```

You also need a MySQL 8.0 database to point at. Either run only the database from
Docker —

```bash
docker compose -f deploy/docker/docker-compose.yml up -d db
```

— and set `APP_DB_HOST=localhost`, `APP_DB_PORT=3307` in `.env`, or use your own
MySQL 8.0 instance. The database user, password and name in `.env` must match it.

```bash
# 5. Apply migrations (creates every table)
alembic upgrade head

# 6. Create the first administrator BEFORE opening public registration
python scripts/bootstrap_admin.py --email you@example.com
#    the password is read securely from the terminal, never a command-line argument

# 7. Run the API
uvicorn src.presentation.api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is now at http://localhost:8000 with docs at `/docs` and health at
`/health`.

### B2. Run the test suite

```bash
# unit tests (no database needed) with coverage
pytest tests/unit -m "not integration and not concurrency and not slow" --cov=src

# integration + concurrency tests need a REAL MySQL: set APP_DB_HOST (and the
# other APP_DB_* values) first, or they self-skip.
export APP_DB_HOST=localhost APP_DB_PORT=3307   # Windows: $env:APP_DB_HOST="localhost"
pytest tests/integration tests/concurrency -m "integration or concurrency"
```

CI additionally runs linting, formatting, static types and a security scan:

```bash
ruff check src tests
ruff format --check src tests
mypy src
bandit -r src -c pyproject.toml --severity-level medium
```

### B3. Frontends

There are two Vue 3 + Vite + TypeScript clients. Each is a separate project:

```bash
# Customer / ordering app
cd frontend
npm install
npm run dev          # Vite dev server, http://localhost:5173

# Membership (auth) app — separate project, separate port
cd ../src/presentation/membership
npm install
npm run dev          # binds 127.0.0.1; see the printed URL
```

The dev servers expect the API on http://localhost:8000 and are allowed by the
`APP_CORS_ORIGINS=http://localhost:5173` default. To build static assets instead
of running a dev server, use `npm run build` in each project.

---

## Regenerating the API documentation

The committed `docs/api/openapi.json` is generated from the running app and must
be re-exported after any route change (requirement FR-XX-04):

```bash
APP_ENVIRONMENT=development APP_JWT_SECRET_KEY=<any 32+ char value> \
  python scripts/export_openapi.py --output docs/api/openapi.json
```

(On Windows PowerShell, set the two `$env:` variables first, then run the
`python scripts/export_openapi.py --output docs/api/openapi.json` line.)

> The committed file uses LF line endings; a regeneration on Windows may write
> CRLF and show as a whole-file diff. Normalise line endings before committing,
> or regenerate on Linux/CI.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `pytest` fails immediately with an `INTERNALERROR` or a `DeprecationWarning` turned into an error during collection | You are on Python 3.13/3.14, not 3.11. A dependency emits a deprecation warning that `filterwarnings = ["error"]` escalates. | Use a **Python 3.11** virtual environment. |
| `OperationalError: no such table: ...` | Migrations were not applied. | Run `alembic upgrade head`. The Docker path does this automatically on container start. |
| `alembic` reports **multiple heads** | Two migrations share a revision number (this has happened on this project). | Check `src/data/migration/versions/`; renumber the later one and re-run. |
| `InsecureKeyLengthWarning` escalated to an error in `test_security.py` | `APP_JWT_SECRET_KEY` is shorter than 32 bytes. | Set a strong secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| API container starts but every request 500s | The database was not ready, or `.env` points at the wrong host/port/user. | In Docker the API waits for the DB healthcheck; manually, confirm `APP_DB_*` match your MySQL. |
| `pip install` hangs on Windows | Slow direct access to `pypi.org`. | Use the Aliyun mirror (see B1). |
| Port already in use (8000 / 3307 / 5173 / 8081) | Another service holds the port. | Change the host-side port in `docker-compose.yml`, or stop the conflicting service. |

---

## What "installed and running" means for this PoC

A successful install gives you: a MySQL 8.0 database with all tables created by
the migration chain; the FastAPI application serving `/health` (200),
`/docs` and the `/api/v1/*` endpoints; at least one administrator account; and
the two Vue frontends able to reach the API. See the user manual under
`docs/user-manual/` for how to exercise each module once the stack is up.

> **Known limitations of the current build** (tracked, not install blockers): the
> ordering and analytics backend modules are partially implemented, and the
> loyalty module is not yet wired into the running application. Installing and
> starting the stack works; some module endpoints return placeholder data. The
> group is tracking these against the proposal deadlines.
