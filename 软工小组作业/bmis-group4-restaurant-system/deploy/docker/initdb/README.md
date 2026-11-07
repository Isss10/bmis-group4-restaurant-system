# MySQL first-run initialisation scripts
#
# Files here run **once**, alphabetically, the first time the database volume is
# created (see docker-compose.yml). They are the place for seed data that every
# team member needs: lookup tables, sample menu items, a demo staff account.
#
# Rules
# -----
# * Name files so execution order is obvious: `01_`, `02_`, …
# * Supported extensions: `.sql`, `.sh`, `.sql.gz`.
# * These run as root against an empty database — do not put `CREATE DATABASE`
#   or `USE` here; `MYSQL_DATABASE` from compose already selected it.
# * Idempotency matters less than you would think (they only run on a fresh
#   volume), but prefer `INSERT IGNORE` / `ON DUPLICATE KEY UPDATE` anyway so a
#   partially-applied run can be retried.
# * **No real data.** This directory is committed to a public repository.
#
# To re-run these after the first init, delete the volume:
#
#     docker compose -f deploy/docker/docker-compose.yml down -v
#
# Suggested starting point (owned by the database layer author, per README §6):
#
#     01_lookup_tables.sql     — roles, reservation states, membership tiers
#     02_seed_menu.sql         — sample dishes and categories for the ordering module
#     03_seed_tables.sql       — restaurant tables/seats for the reservation module
#     04_seed_demo_users.sql   — one account per role, with bcrypt-hashed passwords
#
# ⚠️ The demo accounts must use a **bcrypt hash**, never a plaintext password,
# and the plaintext must be documented in docs/user-manual/ rather than here.
