<!--
  AUTHOR: M10 (RONG CONG)   SUPPORT: M4
  TARGET: 4 pages           DUE: 27 Nov 2026
  STATUS: draft v1 (23 Nov 2026) — authentication and roles implemented; loyalty prototype pending integration
  SOURCES: docs/design/MEMBERSHIP_MEMBER10.md, docs/api/MEMBERSHIP_AUTH.md,
           docs/requirements/REQUIREMENTS.md §§4.3, 6, PR #10 and M4's loyalty handoff
-->

# 8. Implementation — Membership & Loyalty

Objective (c) connects a customer's account to the services that use that identity.
Member10 implements authentication, role enforcement and auditing of account
changes. Member4 owns the loyalty ledger, tiers, coupons and their business audits.
Authentication was merged in PR #10 (`44f3ae4`). This chapter describes the running
authentication implementation at the 23 November main baseline (`7d08e38`) and
records the loyalty prototype and its integration dependencies in §§8.3–8.5.

## 8.1 Registration and authentication (FR-MEM-01)

The application recognises `customer`, `waiter`, `manager` and `admin`. Public
registration creates a customer. The server validates and normalises the email
and relies on a database uniqueness constraint to enforce one account for the
normalised address even when registrations race. A local bootstrap creates the
first administrator. Subsequent staff and admin accounts require an authenticated
administrator. This keeps the public request from choosing an elevated role.

A password is stored as a bcrypt hash. The work factor of 12 makes password
verification deliberately expensive, and the login path verifies the password
before taking the database write lock. Minimum length and bcrypt's 72-byte input
bound are enforced before hashing. Unknown accounts, bad passwords and inactive
accounts receive the same public authentication failure. Registration and login
are limited to five attempts per minute per source IP by default. The current
in-process limiter counts requests within one API process.

Login issues a 60-minute signed access token and creates a session with a seven-day
absolute refresh expiry. The access token carries the account identifier, role,
session identifier and authentication version. The refresh credential is random
and stored in the browser as a restricted `HttpOnly`, `SameSite=Strict` cookie,
with `Secure` enabled in production. The database holds a digest of the credential.
The browser sends the associated CSRF value when renewing or ending that session.

Renewal rotates the credential in one transaction and saves the old digest until
session expiry. If a previous credential is submitted again, the server revokes
the session, including any successor already issued from it. The session's original
expiry remains in effect. Logout terminates the current session. This design accepts
a database read during authorisation so that a revoked or deactivated session loses
access before its signed access token expires. Chapter 4 §4.6 shows the interactions
among browser, API, application service and data layer.

## 8.2 Role-based access control (FR-MEM-02)

Each protected operation specifies the roles it accepts. The server verifies the
signed token and checks the stored session, account status, current role and
authentication version. It then applies the endpoint's role and resource checks.
Missing credentials produce `401 / 30001`. Invalid, expired or revoked credentials
produce `401 / 30002`. A caller with a valid session and insufficient permission
receives `403 / 30003`. Chapter 2, Table 2.8 gives the shared permission matrix.

The current identity and profile operations look up the account identified by the
session. Reservation creation derives ownership from that same identity. When a
customer cancels a reservation, ownership is checked while its row is locked and
before the update. Review submission also checks that the submitted customer ID
matches the session. That check establishes author identity. The completed-order
and dish eligibility checks belong to the review and ordering services, with their
own acceptance evidence.

Role and activation changes use a version supplied by the administrator's form.
If another request has already changed the record, the stale edit returns `20004`
and the client reloads before retrying. Authentication writes take a shared policy
row lock. That lock serialises the check for the last active administrator with the
change itself, so two simultaneous permission changes cannot both remove the last
administrator. A role change or deactivation revokes the affected account's old
sessions in the same transaction. The prototype trades parallel authentication
writes for a small, predictable critical section.

Table 8.1. Auth and account endpoints in the running application.

| Method and path (under `/api/v1`) | Access | Purpose |
|---|---|---|
| POST `/auth/register`, `/auth/login` | Public | Create a customer and sign a user into a session. |
| GET `/auth/csrf` | Browser with session cookie | Retrieve proof for the next cookie-authenticated operation. |
| POST `/auth/refresh`, `/auth/logout` | Current session cookie and CSRF proof as applicable | Rotate or revoke the current session. |
| GET `/auth/me`, `/membership/profile` | All authenticated roles, own account | Return current identity or the caller's profile. |
| GET, POST `/users` | Admin | List accounts within pagination bounds or provision an account. |
| PATCH `/users/{id}/role`, `/users/{id}/status` | Admin | Change role or active status using the expected record version. |

## 8.3 Append-only points ledger (FR-MEM-03)

The agreed data model records earnings, redemptions, expirations and adjustments as
separate entries. This preserves the event that changed the balance and allows an
auditor to reconstruct it. A balance stored as a single mutable field would require
extra coordination for competing redemptions and a second mechanism to explain
earlier changes. A ledger preserves that history, while the service still needs
transactional allocation to prevent two requests from spending the same points.

Member4's prototype associates each earning event with its order identifier and
rejects duplicate earning from a retried order-completion event. Each earning lot
has its own expiry. Redemption consumes eligible lots and adds allocation records,
while expiry can remove the remaining portion of a lot without rewriting the
original earn event. For example, after earning 8 points and redeeming 3, expiry of
the original lot removes the remaining 5. The ledger keeps all three movements.

The proposed rule awards one point per complete ¥10 spent and expires points after
12 months. The prototype awards the integer part of paid amount divided by ¥10 and
sets the expiry exactly 365 days after earning. The distinction is relevant across a
leap day. The requirements register leaves the expiry convention and earn policy
open for a group decision. Member4 and Member10 need a shared contract entry and
boundary examples before the team can accept the result as policy.

## 8.4 Membership tiers (FR-MEM-04)

The loyalty prototype derives the tier from cumulative qualifying completed-order
spend. Using spend keeps a customer's tier stable when they redeem points. The
candidate seed data assigns `BRONZE`, `SILVER`, `GOLD` and `PLATINUM` at spend
thresholds of ¥0, ¥500, ¥2,000 and ¥5,000, with corresponding discounts of 0%, 2%,
5% and 8%. The prototype chooses the highest active qualifying tier. These are
prototype thresholds for the **Should** requirement. The team's acceptance depends
on agreeing the final values and exercising them through the running application.

## 8.5 Coupons and discount stacking (FR-MEM-05)

The draft stacking policy allows a single `EXCLUSIVE` coupon or a compatible set
of `STACKABLE` coupons. For stacking, the prototype applies the tier discount
first, then percentage coupons against the remaining payable amount, and then
fixed-value coupons. It checks the minimum spend against the original subtotal.
It uses a stable ordering within each coupon type, rounds monetary amounts to
cents and caps discounts at the payable balance. Ownership, availability and
validity checks apply before calculation. An exclusive coupon excludes another
coupon. The prototype still applies the tier discount in that case.

For a ¥100 order with no tier discount, a 10% coupon followed by a ¥20 coupon
leaves ¥70 payable. Reversing the order leaves ¥72 payable, so ordering is part of
the contract the customer sees. With an eligible 5% tier discount, a 10% coupon
and a ¥20 coupon, the prototype produces ¥65.50. The coupon ordering rule remains
open in Chapter 2 §2.6. An approved rule should give clear expected amounts for
the order of deductions, rounding, exclusivity and the cap.

The points, tier and coupon code is available in the nested M4 upload at this
baseline, together with its own API handoff. Its router, data models and migration
are absent from main's active application tree. The prototype's `0004` migration
number overlaps the live auth revision. Its replacement revision and ordering
integration depend on M4 and M8's work. The Order Service must pass a verified
account and order identifier and the agreed paid amount for completion-linked
earning. A successful test of the prototype supports its calculation design.
End-to-end delivery also requires the running API, an applied migration and a test
of the order-completion handoff.

## 8.6 Auditing membership changes (FR-MEM-06)

Account creation, role changes and activation changes append an audit event in the
same transaction as the mutation. Entries identify the actor, action and target,
include the safe before/after state where applicable and carry the request ID.
Passwords, password hashes and refresh credentials are excluded. For example, a
role-change entry records the previous and new roles, while the session records
are revoked as part of that same change. If the audit write fails, the transaction
rolls back the permission change and session revocation. Chapter 11 covers the
shared audit subsystem. The loyalty acceptance evidence must separately demonstrate
that points adjustments and coupon events commit with their corresponding audit rows.

## 8.7 Frontend and verification

The membership Vue client keeps the access token in memory. On page reload it can
restore the session through the protected cookie and refresh flow. Concurrent
requests share one refresh operation, preventing duplicate rotations from the same
page. The client reads the shared response envelope and uses the returned role to
show the relevant UI. The API supplies the permission decision on every protected
operation. The membership screens cover customer registration and profile access,
as well as administrator account creation, role and status changes.

The API tests exercise registration, the refresh lifecycle, invalidation, role
changes and failure atomicity. The cross-module authorisation tests use tokens from
real login requests and check both the response and stored reservation ownership.
The schema tests check the relationship between migrations and model metadata. PR
#10's [MySQL CI run](https://github.com/Isss10/bmis-group4-restaurant-system/actions/runs/42481861999)
exercised duplicate registration, refresh and administrator races, transactional
rollback and the membership migration. At the current main baseline, the integration
file contains a placeholder. This follow-up restores the real cases in isolated
test schemas. Chapter 12 should use the new CI run when recording their outcome.
The frontend workflow runs type checking, session handling tests and a production
build. The seven-state reservation handoff updates the booking fixture and
historical migration checks while preserving the authentication acceptance
conditions. Chapter 12 records execution evidence and the acceptance still
required for full T4.
