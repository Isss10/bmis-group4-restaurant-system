<!--
Fill in every section. Delete the guidance comments before submitting.
A PR with empty sections will be returned for completion.
-->

## What

<!-- One or two sentences: what does this PR change? -->

## Why

<!-- What problem does it solve? Link the proposal objective or issue.
     Example: "Objective (d) — guarantee concurrency-correct booking." -->

Relates to: <!-- objective / issue number -->

## How to verify

<!-- Concrete steps a reviewer can follow to confirm this works.
     Commands to run, endpoints to call, expected results. -->

1.
2.

## Type of change

- [ ] New feature (`feat`)
- [ ] Bug fix (`fix`)
- [ ] Tests only (`test`)
- [ ] Documentation only (`docs`)
- [ ] Refactor, no behaviour change (`refactor`)
- [ ] Build / CI / tooling (`chore`)

## Checklist

- [ ] Branch is rebased on the latest `main`
- [ ] CI is green
- [ ] New code has tests (unit / integration / concurrency as appropriate)
- [ ] No secrets, passwords, API keys or real personal data committed
- [ ] No leftover debug logging (`console.log`, `print`, `System.out.println`)
- [ ] Public REST endpoints documented in `docs/api/`
- [ ] Back-office changes write audit log entries
- [ ] Database changes are a **new** migration file, not an edit to an existing one
- [ ] User-visible changes reflected in `docs/user-manual/`

## Concurrency / security notes

<!-- Only fill in if this PR touches booking, transactions, authentication,
     authorisation, payments-like logic, or any user-supplied input.
     Otherwise write "N/A". -->

- Does this change affect the booking critical section? <!-- yes/no -->
- Are queries parameterised (no string-concatenated SQL)? <!-- yes/no/N/A -->
- Is the endpoint covered by role-based access control? <!-- yes/no/N/A -->

## Screenshots / output

<!-- For UI changes, add before/after screenshots. For backend changes, paste
     key test output or API responses. -->
