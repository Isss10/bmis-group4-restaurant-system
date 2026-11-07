# Loyalty API

The loyalty API is mounted at `/api/v1/membership`. Authentication and user
administration are separate endpoints; this document only covers completed
loyalty functionality.

The generated [OpenAPI document](openapi.json) is the source of truth for field
validation and response schemas.

## Permissions

| Operation group | JWT role |
|---|---|
| Current member, points, owned coupons, quote/redeem | `customer` |
| Tier list | any authenticated role |
| Tier/coupon configuration and points administration | `manager`, `admin` |
| Completed-order integration event | `waiter`, `manager`, `admin` |

Customer routes derive the member identity from the verified JWT `sub` claim.

## Completed endpoints

| Contract ID | Method | Path | Request type | Response type |
|---|---|---|---|---|
| LOY-01 | GET | `/api/v1/membership/me` | none | `MembershipSummaryOut` |
| LOY-02 | GET | `/api/v1/membership/points` | pagination query | `Page<PointsLedgerOut>` |
| LOY-03 | POST | `/api/v1/membership/points/redeem` | `PointsRedeemIn` | `PointsRedeemOut` |
| LOY-04 | GET | `/api/v1/membership/tiers` | none | `TierOut[]` |
| LOY-05 | POST | `/api/v1/membership/tiers` | `TierConfigIn` | `TierOut` |
| LOY-06 | GET | `/api/v1/membership/coupons` | none | `CouponOut[]` |
| LOY-07 | POST | `/api/v1/membership/coupons` | `CouponCreateIn` | `CouponDefinitionOut` |
| LOY-08 | POST | `/api/v1/membership/coupons/issue` | `CouponIssueIn` | `CouponIssueOut` |
| LOY-09 | POST | `/api/v1/membership/coupons/quote` | `CouponQuoteIn` | `CouponQuoteOut` |
| LOY-10 | POST | `/api/v1/membership/coupons/redeem` | `CouponRedeemIn` | `CouponRedeemOut` |
| LOY-11 | POST | `/api/v1/membership/admin/points/adjust` | `PointsAdjustIn` | `PointsAdjustOut` |
| LOY-12 | POST | `/api/v1/membership/admin/points/expire` | none | `ExpiryRunOut` |
| LOY-13 | POST | `/api/v1/membership/events/orders/{order_id}/completed` | `OrderCompletedIn` | `OrderCompletedOut` |

Every operation carries `x-module: loyalty`, `x-contract-id` and
`x-implementation-status: implemented` in OpenAPI.

## Frontend wrappers

| Contract ID | Wrapper |
|---|---|
| LOY-01 | `getMembershipSummary()` |
| LOY-02 | `listPoints(params)` |
| LOY-03 | `redeemPoints(body)` |
| LOY-04 | `listTiers()` |
| LOY-05 | `configureTier(body)` |
| LOY-06 | `listCoupons()` |
| LOY-07 | `createCoupon(body)` |
| LOY-08 | `issueCoupon(body)` |
| LOY-09 | `quoteCoupons(body)` |
| LOY-10 | `redeemCoupons(body)` |
| LOY-11 | `adjustPoints(body)` |
| LOY-12 | `expirePoints()` |
| LOY-13 | `completeOrderForLoyalty(orderId, body)` |

Generate request and response types from `openapi.json`; do not duplicate the
schemas in hand-written client types.

## Business invariants

- Points use append-only `EARN`, `REDEEM`, `EXPIRE` and `ADJUST` events.
- Redemptions and expirations allocate against positive point lots and never
  overwrite an existing ledger row.
- A completed order and a points redemption use their associated order id as an
  idempotency key.
- The tier is derived from cumulative qualifying spend, not spendable balance.
- Stackable coupons apply percentage discounts before fixed-amount discounts.
- An exclusive coupon cannot be combined with another coupon.
- Coupon redemption locks ownership rows and binds them to one order.
- Total discounts cannot exceed the order subtotal.
- Loyalty mutations and their audit rows use the caller's transaction.

## Order-completion integration

`LOY-13` is available for separate-process integration. When order completion
and loyalty updates run in the same process, call
`LoyaltyService.award_completed_order()` inside the caller's existing session so
the order update, points event and audit row commit atomically.
