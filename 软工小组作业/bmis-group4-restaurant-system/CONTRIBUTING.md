# Contributing Guide

This guide keeps ten people working on one codebase without stepping on each other. Read it once
before your first pull request.

---

## 1. Getting access

1. The repository owner (**Isss10**) invites you as a collaborator:
   `Settings → Collaborators and teams → Add people`
2. You receive an email from GitHub and click **View invitation** (invitations expire after 7 days).
   If you miss it, go to https://github.com/notifications while logged in.
3. Confirm you can see the repository at
   https://github.com/Isss10/bmis-group4-restaurant-system

> Your GitHub display name does not need to match your real name, but please tell the group which
> GitHub account is yours so contributions are attributed correctly in the workload profile.

---

## 2. First-time local setup

```bash
# Clone
git clone git@github.com:Isss10/bmis-group4-restaurant-system.git
cd bmis-group4-restaurant-system

# Set your identity (must match the email on your GitHub account, or your commits show as unlinked)
git config user.name  "Your Name"
git config user.email "you@example.com"
```

### If SSH does not work for you

Generate a key and add the public part to GitHub (`Settings → SSH and GPG keys → New SSH key`):

```bash
ssh-keygen -t ed25519 -C "you@example.com"
cat ~/.ssh/id_ed25519.pub      # copy this into GitHub
ssh -T git@github.com          # should greet you by username
```

### If port 22 is blocked on your network

Route SSH over port 443 by adding this to `~/.ssh/config`:

```
Host github.com
    HostName ssh.github.com
    Port 443
    User git
```

### HTTPS alternative

```bash
git clone https://github.com/Isss10/bmis-group4-restaurant-system.git
```

HTTPS will prompt for credentials. Use a **Personal Access Token**, not your password
(`Settings → Developer settings → Personal access tokens → Tokens (classic)`). Grant the `repo`
scope.

---

## 3. Branch model

```
main                    ← protected, always deployable. Merge only via approved PR.
├── feature/reservation-booking-flow
├── feature/ordering-menu-browsing
├── feature/membership-points-ledger
├── feature/review-bayesian-ranking
├── feature/analytics-manager-dashboard
├── feature/db-schema-and-migrations
├── feature/staff-backend-reservation-list
├── feature/engineering-quality-ci-docker
├── fix/booking-conflict-race-condition
├── docs/user-manual
└── test/concurrency-booking
```

### Naming rules

| Prefix | Use for |
|--------|---------|
| `feature/` | New functionality |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `test/` | Adding or fixing tests |
| `refactor/` | Restructuring without behaviour change |
| `chore/` | Build, CI, dependencies, tooling |

Always lowercase, words separated by `-`, and start with the module you own
(`reservation`, `ordering`, `membership`, `review`, `analytics`, `db`, `staff`, `quality`).

### Rules

- **One branch = one coherent task.** Do not mix the reservation state machine with a README rewrite.
- **Branch from an up-to-date `main`.**
- **Never push directly to `main`.**
- Keep branches short-lived — merge within a few days, or they rot.

---

## 4. Daily workflow

```bash
# 1. Start from fresh main
git checkout main
git pull origin main
git checkout -b feature/reservation-booking-flow

# 2. Work. Commit often, in small logical steps.
git add src/application/reservation/
git commit -m "feat(reservation): add booking flow with conflict check"

# 3. Before pushing, rebase on the latest main to keep history linear
git fetch origin
git rebase origin/main

# 4. Push
git push -u origin feature/reservation-booking-flow
```

Then open a Pull Request on GitHub.

### If a rebase goes wrong

```bash
git rebase --abort      # returns you to the state before the rebase. Nothing is lost.
```

---

## 5. Commit messages — Conventional Commits

```
<type>(<scope>): <subject>

[optional body — what and why, not how]
```

| Type | Meaning |
|------|---------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `test` | Adding or fixing tests |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `chore` | Build process, CI, dependencies, tooling |

Scope = the module: `reservation`, `ordering`, `membership`, `review`, `analytics`, `db`, `staff`,
`api`, `ci`, `docker`.

### Examples

```
feat(reservation): add temporary seat hold with automatic expiry

Holds are released by a scheduled job after 10 minutes if the booking is
not confirmed, preventing tables from being locked indefinitely.
```

```
fix(db): add unique constraint on (table_id, time_slot, date)

Optimistic locking alone still allowed a duplicate booking under high
concurrency. The unique constraint is the safety net required by the
proposal's Objective (d).
```

```
test(concurrency): verify only one of 50 simultaneous bookings succeeds
```

### Bad commit messages — do not use these

`update`, `fix stuff`, `wip`, `change`, `1`, `asdf`, `修改`, `test`

---

## 6. Pull requests

1. Push your branch and click **Compare & pull request**.
2. Fill in the PR template: what changed, why, how to verify, and which proposal objective it serves.
3. **CI must pass.** It runs lint, unit tests, integration tests and coverage on every PR.
4. Request a review from at least one teammate — ideally whoever owns the adjacent module.
5. Address review comments by pushing new commits to the same branch (the PR updates automatically).
6. After approval, merge with **Squash and merge**, then delete the branch.

### Before requesting review, check yourself

- [ ] Branch is rebased on the latest `main`
- [ ] CI is green
- [ ] New code has tests (unit / integration / concurrency as appropriate)
- [ ] No secrets, passwords, API keys or personal data committed
- [ ] No `console.log` / `print` debugging left behind
- [ ] Public REST endpoints documented in `docs/api/`
- [ ] Back-office changes write audit log entries
- [ ] PR is small enough to review (< 400 changed lines where practical)

---

## 7. Code review etiquette

**As a reviewer**

- Review within 24 hours. A blocked teammate is a blocked project.
- Comment on the code, not the person. Say what you'd like changed and why.
- Distinguish blocking issues from nitpicks — prefix optional suggestions with `nit:`.
- Approve when it's good enough, not when it's perfect.

**As an author**

- Don't take comments personally; they're about the code.
- Reply to every comment, even just "done" or an explanation of why you disagree.
- If you disagree, discuss it. Escalate to the group if unresolved.

---

## 8. Coordination rules for shared code

These are the places ten people collide most. Agree before you touch them.

| Shared artefact | Owner | Rule |
|-----------------|-------|------|
| Database schema (`src/data/schema/`) | YUANYUAN XUE | **Never edit someone else's migration.** Add a new migration file. Coordinate column/table changes in the group chat first. |
| REST API contracts (`docs/api/`, `src/presentation/api/`) | YAN ZHANG | Agree the endpoint shape in `docs/api/` **before** writing client code. Breaking changes need a heads-up to all frontend owners. |
| CI workflow (`.github/workflows/`) | YAN ZHANG | Changes need review from the owner. A broken pipeline blocks all ten of you. |
| Docker / deploy (`deploy/`) | YAN ZHANG | Same as CI. |
| Reservation state machine | KEYING CHEN | The staff backend and analytics both read reservation status. Any new state or transition must be announced. |

**Rule of thumb:** if your change alters an interface someone else depends on, post in the group
chat *before* you open the PR, not after.

---

## 9. Merge conflicts

Conflicts happen when two branches edit the same lines. Handle them calmly:

```bash
git fetch origin
git rebase origin/main
# Git stops at the conflicting commit and lists the files.
# Open each file, resolve the <<<<<<< ======= >>>>>>> markers, then:
git add <resolved-file>
git rebase --continue
```

- Never resolve a conflict by blindly accepting your own side — you may delete a teammate's work.
- If the conflict is in code you don't own, ask its owner.
- Prevent conflicts: keep branches small and short-lived, and rebase on `main` daily.

---

## 10. What must never be committed

- Passwords, API keys, tokens, `.env` files with real values (use `.env.example` with placeholders)
- Personal data of real people
- IDE settings, `node_modules/`, build output, database dumps, log files
- Large binaries (videos, presentation recordings) — use the course submission channel instead

`.gitignore` already covers the common cases. If you find something missing, add it in a
`chore:` commit.

---

## 11. Definition of Done

A task is complete only when:

- [ ] Code is merged into `main` through an approved PR with green CI
- [ ] Tests exist and pass, including the concurrency test for booking-related changes
- [ ] Coverage report updated
- [ ] Public REST endpoints documented in `docs/api/`
- [ ] Back-office changes produce audit log entries
- [ ] OWASP Top 10 considerations addressed (input validation, parameterised queries, authn/authz,
      no secrets in code, rate limiting where applicable)
- [ ] User manual section updated in `docs/user-manual/` if the change is user-visible

---

## 12. Useful commands

```bash
git status                       # What is changed / staged?
git log --oneline --graph -20    # Recent history
git branch -a                    # All branches, local and remote
git diff main..HEAD              # Everything your branch adds
git stash / git stash pop        # Park unfinished work temporarily
git restore <file>               # Discard unstaged changes to one file (careful — irreversible)
```

---

## 13. Stuck?

1. Read the error message fully — the answer is usually in it.
2. Search the project's existing code and `docs/` for a similar case.
3. Search online for the exact error text.
4. Ask in the group chat with: what you were doing, the exact error, and what you already tried.

Asking early is cheaper than silently blocking for two days.
