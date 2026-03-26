# Architecture - Family Budget App

## What This Project Does

A monthly household budgeting tool. Users log in, set per-category budget targets for a given month, upload bank/credit-card CSV exports to populate transactions, and review actuals vs. budget. Budget edits are recorded in an audit log with a required explanation. CSV imports use an LLM to identify the date/description/amount columns and to auto-categorize each transaction against the user's active category list.

Budget targets and transactions are constrained to **editable year-months** (current, the previous month while still in its 7-day grace period, and the next 12 months). Locked year-months are read-only by default; an authenticated **admin override** lets privileged users mutate them. Budget-target mutations via override are recorded in the audit log; transaction mutations are not (see **Audit scope**).

## Project Layout

```
budget/              React + TypeScript frontend (Vite)
    src/
        pages/       Top-level route pages
        components/  Shared UI components
        api.ts       Typed API client
        auth.ts      Cognito PKCE auth + token refresh
        ...
lambda/src/corderohq/
    budget_handler.py      Lambda entrypoint + HTTP routing
    budget/csv_import.py   LLM-driven CSV column mapping + categorization
    aws/dynamodb.py        Table wrappers and summary computation
infra/lib/
    budget-dynamodb-stack.ts   DynamoDB tables
    budget-web-stack.ts        Cognito client, Lambda, API Gateway, CloudFront
```

## Infrastructure Overview

The infrastructure is split into two CDK stacks that build on the shared `PlatformStack` (DNS, TLS, Cognito user pool).

### BudgetDynamoDbStack

Owns the four DynamoDB tables. Separated from the web stack so app redeploys don't risk the data. All tables are pay-per-request with point-in-time recovery enabled. Removal policy is `RETAIN` in prod and `DESTROY` in dev.

### BudgetWebStack

The application layer. Creates a Cognito app client (PKCE, no client secret), a Python 3.13 Lambda handler with DynamoDB read/write and SSM `GetParameter` permissions, an API Gateway HTTP API with a Cognito JWT authorizer, and a CloudFront distribution that fronts both the React frontend and the API.

The CloudFront distribution has three behaviors:

- **Default** → S3 origin serving the static React build (cache disabled in dev).
- **`/api/*`** → API Gateway origin, all viewer headers forwarded (so the `Authorization` Bearer token reaches the Lambda), cache disabled.
- **`/oauth2/*`** → Cognito hosted-UI domain origin, cache disabled.

Routing `/oauth2/*` through CloudFront keeps Cognito on the same origin as the app, so refresh-token requests can use same-origin cookies/headers without CORS.

### How They Connect

```
PlatformStack (DNS, TLS, shared Cognito User Pool)
    |
    +-- BudgetDynamoDbStack (4 DynamoDB tables)
    |       |
    +-------+-- BudgetWebStack (Cognito client, Lambda, API Gateway, CloudFront)
```

## Data Model (DynamoDB)

All amounts are stored as **integer millionths of a dollar** (so $12.34 → 12_340_000) to avoid floating-point error. The frontend converts on display.

```
+------------------------+--------------------+------------+-----------------------------+
| Table                  | PK                 | SK         | Notes                       |
+------------------------+--------------------+------------+-----------------------------+
| Category-{stage}       | categoryId         | —          | categoryId is ULID. Fields: |
|                        |                    |            | name, active, timestamps,   |
|                        |                    |            | nameHistory (list of        |
|                        |                    |            | {previousName, replacedAt   |
|                        |                    |            | ISO-8601 UTC}). Soft-delete |
|                        |                    |            | via active=False. Names are |
|                        |                    |            | unique case-insensitive     |
|                        |                    |            | across active + inactive —  |
|                        |                    |            | see **Category name        |
|                        |                    |            | uniqueness** below.         |
+------------------------+--------------------+------------+-----------------------------+
| Budget-{stage}         | yearMonth          | categoryId | yearMonth is YYYY-MM.       |
|                        |                    |            | amount (millionths). One    |
|                        |                    |            | row per category per month. |
+------------------------+--------------------+------------+-----------------------------+
| Transactions-{stage}   | yearMonth          | sortId     | sortId = {transactionDate}# |
|                        |                    |            | {ULID}. Fields:             |
|                        |                    |            | transactionDate,            |
|                        |                    |            | description, amount         |
|                        |                    |            | (signed millionths;         |
|                        |                    |            | positive = expense,         |
|                        |                    |            | negative = income or        |
|                        |                    |            | return), categoryId. Sort   |
|                        |                    |            | key sorts chronologically   |
|                        |                    |            | within a month.             |
+------------------------+--------------------+------------+-----------------------------+
| BudgetAuditLog-{stage} | "AUDIT"            | sortId     | Single-partition design so  |
|                        |                    |            | recent-N queries are one    |
|                        |                    |            | Query with                  |
|                        |                    |            | ScanIndexForward=false. PK  |
|                        |                    |            | is the literal string       |
|                        |                    |            | "AUDIT". sortId is ULID     |
|                        |                    |            | (sortable by time). Fields: |
|                        |                    |            | changedAt (ISO-8601 UTC     |
|                        |                    |            | timestamp), effectiveYear-  |
|                        |                    |            | Month (nullable),           |
|                        |                    |            | categoryId, action (CREATE/ |
|                        |                    |            | UPDATE/PIN/UNPIN/CATEGORY_  |
|                        |                    |            | HARD_DELETE), explanation,  |
|                        |                    |            | user ({sub, email,          |
|                        |                    |            | username}; see **Audit user |
|                        |                    |            | identity**), override       |
|                        |                    |            | (bool), changes (shape      |
|                        |                    |            | varies by action). CREATE/  |
|                        |                    |            | UPDATE come from /replace   |
|                        |                    |            | on dense months; PIN/UNPIN  |
|                        |                    |            | from /pin OR from           |
|                        |                    |            | deactivation dropping       |
|                        |                    |            | future pins; CATEGORY_HARD_ |
|                        |                    |            | DELETE from DELETE          |
|                        |                    |            | /api/categories/{id} with   |
|                        |                    |            | effectiveYearMonth null.    |
+------------------------+--------------------+------------+-----------------------------+
```

### Category name uniqueness

The Category-{stage} schema has no PK or GSI on `name`, so case-insensitive uniqueness is enforced **in application code, not in DynamoDB**:

1. On every `POST /api/categories` and `PUT /api/categories/{id}` (rename), the handler `Scan`s the Category table, lower-cases each existing `name`, and checks for a match against the lower-cased incoming name. If a match is found, returns `409 Conflict`. Otherwise proceeds with the write.

This approach is **racy**. Two simultaneous creates with the same name will both pass the uniqueness check independently and both write their rows — leaving the table with two categories sharing a name. At household scale this is a non-issue: a single user typing into a single browser tab won't race themselves. The implementation must include a prominent comment at the uniqueness-check call site flagging the race so future maintainers don't assume it's airtight.

**If this ever needs to scale beyond single-household use**, the refactor path is:

- Use the sentinel-item pattern in the same table: write the Category row AND a second item with `PK = "NAME#{lowercased}"` (and a placeholder SK such as `_` since the table currently has no SK) in one `TransactWriteItems` call, each with `ConditionExpression: attribute_not_exists(PK)`. The transaction fails atomically if any other writer has already claimed the name. This is the correct, race-free design but adds enough complexity (the schema gains a polymorphic PK, the rename path has to also re-issue the sentinel) that it's not worth it for now.

## Request Flow

```
Browser --> CloudFront --> S3 (React app)
                |
                +--> /api/*    --> API Gateway --> Lambda (budget_handler.handler)
                |     (JWT auth via Cognito User Pool authorizer)
                |
                +--> /oauth2/* --> Cognito hosted UI (same-origin)
```

The frontend uses PKCE authorization-code flow with the Cognito hosted UI. After callback, the SPA stores tokens, sends the access token as `Authorization: Bearer ...` on API calls, and uses a single-flight refresh on 401.

## API Routes (Lambda)

All routes are JWT-authenticated and namespaced under `/api`. The handler routes by `(method, rawPath)` to private functions.

```
+--------+------------------------------------------+------------------------------------+
| Method | Path                                     | Purpose                            |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/categories?include_inactive=true    | List categories (active only by    |
|        |                                          | default).                          |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/categories/{id}?deletion_preview=   | Admin-only. Returns the hard-      |
|        | true                                     | delete impact summary (counts of   |
|        |                                          | Budget rows, Transactions, locked  |
|        |                                          | months affected, audit entries     |
|        |                                          | that will become unresolvable).    |
|        |                                          | See **Hard delete semantics**.     |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/categories                          | Create category. Body requires     |
|        |                                          | name and initialTarget (non-zero,  |
|        |                                          | non-negative integer millionths).  |
|        |                                          | If the current year-month is       |
|        |                                          | dense, creates a row at            |
|        |                                          | initialTarget in it.               |
+--------+------------------------------------------+------------------------------------+
| PUT    | /api/categories/{id}                     | Rename category. Appends a         |
|        |                                          | nameHistory entry capturing the    |
|        |                                          | previous name and replacedAt time. |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/categories/{id}/deactivate          | Soft-delete. Returns {category,    |
|        |                                          | affectedMonths} where              |
|        |                                          | affectedMonths lists future months |
|        |                                          | with an explicit pin for this      |
|        |                                          | category. Body {confirm: bool}.    |
|        |                                          | If confirm=true, the deactivation  |
|        |                                          | batch-deletes those future pins    |
|        |                                          | and writes one UNPIN audit entry   |
|        |                                          | per dropped pin. If confirm is     |
|        |                                          | absent or false and                |
|        |                                          | affectedMonths is non-empty,       |
|        |                                          | returns 409 so the UI can prompt.  |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/categories/{id}/reactivate          | Reactivate a deactivated category. |
|        |                                          | Future pins dropped at             |
|        |                                          | deactivation are NOT restored.     |
+--------+------------------------------------------+------------------------------------+
| DELETE | /api/categories/{id}                     | Hard delete. Admin-only            |
|        |                                          | (budget-admin-{stage} group claim  |
|        |                                          | required). Cascade-deletes the     |
|        |                                          | Category row, every Budget row     |
|        |                                          | referencing it (all year-months,   |
|        |                                          | including locked), and every       |
|        |                                          | Transaction referencing it (all    |
|        |                                          | year-months, including locked).    |
|        |                                          | Writes a CATEGORY_HARD_DELETE      |
|        |                                          | audit entry. Body requires         |
|        |                                          | confirm=true, confirmName matching |
|        |                                          | the current category name, and    |
|        |                                          | explanation. Hidden from the       |
|        |                                          | normal categories page. See        |
|        |                                          | **Hard delete semantics**.         |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/budget/{YYYY-MM}                    | Get targets for a month. For dense |
|        |                                          | months (locked/grace/current),     |
|        |                                          | returns the stored rows directly.  |
|        |                                          | For future months, returns         |
|        |                                          | resolved effective values per      |
|        |                                          | category with a `pinned: bool`     |
|        |                                          | flag indicating whether the value  |
|        |                                          | came from an explicit pin at this  |
|        |                                          | month or from walking back. Lazy   |
|        |                                          | hydration runs here if the current |
|        |                                          | month is not yet dense — see       |
|        |                                          | **Carry-Forward**.                 |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/budget/{YYYY-MM}/replace            | Dense-month write (current, grace, |
|        |                                          | or — via override — locked).       |
|        |                                          | Replace-all semantics; body must   |
|        |                                          | include every category with an     |
|        |                                          | existing row or a non-zero         |
|        |                                          | transaction in this month. Writes  |
|        |                                          | per-category audit entries for     |
|        |                                          | every diff.                        |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/budget/{YYYY-MM}/pin                | Future-month write. Body lists     |
|        |                                          | only the categories the user is    |
|        |                                          | pinning or unpinning. Upsert       |
|        |                                          | semantics; categories omitted      |
|        |                                          | from the body are untouched.       |
|        |                                          | `amount: null` clears a pin.       |
|        |                                          | Returns downstreamPins and         |
|        |                                          | pinMatchesCarriedValue warnings    |
|        |                                          | per category — see **Pin write    |
|        |                                          | semantics**. Writes per-category  |
|        |                                          | audit entries with action=PIN or   |
|        |                                          | action=UNPIN.                      |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/transactions?month=YYYY-MM          | List transactions for a month.     |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/transactions                        | Create one transaction.            |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/transactions/upload                 | Body {csvData}. Returns parsed +   |
|        |                                          | auto-categorized transactions plus |
|        |                                          | per-row validation annotations     |
|        |                                          | (editability, missing category)    |
|        |                                          | for review. Nothing is committed.  |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/transactions/commit                 | Body {rows, override?}. Atomic     |
|        |                                          | batch insert; rejects entire batch |
|        |                                          | if any row falls in a locked       |
|        |                                          | month without an effective         |
|        |                                          | override.                          |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/transactions/update                 | Update mutable fields              |
|        |                                          | (description, amount, categoryId). |
+--------+------------------------------------------+------------------------------------+
| POST   | /api/transactions/delete                 | Body {items: [{yearMonth, sortId}, |
|        |                                          | ...]}. Batch delete.               |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/summary?month=YYYY-MM               | Per-category budgeted vs. actual + |
|        |                                          | totals.                            |
+--------+------------------------------------------+------------------------------------+
| GET    | /api/audit-log?limit=N                   | Recent audit entries. Default N=10,|
|        |                                          | server cap N=200.                  |
+--------+------------------------------------------+------------------------------------+
```

Mutations on transactions use `POST` (not `PUT`/`DELETE`) so CloudFront caching policies don't strip the body.

All responses include strict security headers (`HSTS`, `X-Content-Type-Options`, `X-Frame-Options`, `Cache-Control: no-store`).

All **editability-gated** mutating endpoints (`POST /api/budget/{YYYY-MM}/replace`, `POST /api/budget/{YYYY-MM}/pin`, `POST /api/transactions`, `POST /api/transactions/update`, `POST /api/transactions/delete`, `POST /api/transactions/commit`) accept an optional `override: true` flag in the request body. The flag is honored only if the JWT proves admin group membership (see **Editability and the Admin Override**); otherwise the handler returns `403`. The override flag has no effect on `GET` endpoints — reads are unrestricted for any authenticated user. The other mutating endpoints (`POST /api/categories`, `PUT /api/categories/{id}` rename, `/deactivate`, `/reactivate`) are not editability-gated and do not accept `override`. `DELETE /api/categories/{id}` is admin-only via a different mechanism (no `override` flag; see **Hard delete semantics**).

Budget-target writes produce audit log entries: `/replace`, `/pin`, and `/deactivate` (the latter only when it drops future pins, in which case one `UNPIN` entry is written per dropped pin). `DELETE /api/categories/{id}` also writes a `CATEGORY_HARD_DELETE` entry. Transaction mutations (insert/update/delete/commit), `POST /api/categories`, `PUT /api/categories/{id}` (rename), and `/reactivate` are not audited. See **Audit Scope** below.

`PUT /api/categories/{id}` (rename) is not subject to editability checks — renames are always allowed and update the `nameHistory` list on the Category row so locked-month displays can resolve the name in effect at that time.

## Editability and the Admin Override

The window of mutable year-months is computed server-side on every mutating request. Clients never decide what is editable; the Lambda is the source of truth.

### Constants

```
N_FUTURE_MONTHS = 12
GRACE_PERIOD_DAYS = 7
BUDGET_TZ = "America/New_York"
```

### State function

`editability(yearMonth, now_utc) -> {EDITABLE, GRACE, LOCKED}` where:

1. Convert `now_utc` to `BUDGET_TZ` to obtain `now_et`.
2. `current_ym = (now_et.year, now_et.month)`.
3. If `yearMonth == current_ym`: `EDITABLE`.
4. If `yearMonth` is one of the next `N_FUTURE_MONTHS` after `current_ym`: `EDITABLE`.
5. If `yearMonth` is `current_ym - 1 month` AND `now_et < (first of current_ym + GRACE_PERIOD_DAYS, 00:00 ET)`: `GRACE`.
6. Otherwise: `LOCKED`.

`GRACE` is treated identically to `EDITABLE` for mutation checks; the distinction exists so the frontend can surface a "grace expires in X days" banner.

Note that `EDITABLE` covers both the current year-month and the next 12. The `/pin` endpoint applies a stricter rule on top of editability (must be `EDITABLE` AND `yearMonth > current_ym`), so the current and grace months — both editable — are rejected for `/pin` and routed to `/replace`.

The rollover instant is **midnight ET on day 1** of the new month, regardless of DST. The grace cutoff is **midnight ET on day 8** of the new month.

### Enforcement

| Endpoint | Editability check |
|----------|------------------|
| `POST /api/budget/{YYYY-MM}/replace` | `{YYYY-MM}` must be the current month, GRACE, or — via override — LOCKED |
| `POST /api/budget/{YYYY-MM}/pin` | `{YYYY-MM}` must be strictly in the future — i.e., EDITABLE and `yearMonth > current_ym` (one of the next 12 months). Pinning the current month, the grace month, or any locked month is rejected with `409`; those months are dense and `/replace` is the right endpoint. Override does not unlock `/pin` for non-future months — it has no use here |
| `POST /api/transactions` | `transactionDate`'s year-month must be EDITABLE or GRACE |
| `POST /api/transactions/update` | Both the old and the new `transactionDate`'s year-months must be EDITABLE or GRACE (an update that moves a row across months must satisfy both) |
| `POST /api/transactions/delete` | Each item's `yearMonth` must be EDITABLE or GRACE |
| `POST /api/transactions/commit` | Every row's `transactionDate` year-month must be EDITABLE or GRACE; see **CSV commit semantics** |

On failure the response is `409 Conflict` with a body listing every offending year-month or row. Single-shot mutations report one item; batch mutations report every failing item in one response — no partial commits, no one-error-at-a-time.

### Admin override

Override is a Cognito user-pool group named `budget-admin-{stage}` (`budget-admin-dev`, `budget-admin-prod`, etc.). The stage-specific naming is deliberate: dev admin status does not leak into prod. The Lambda reads its `STAGE` env var and computes the expected group name on every request.

The API Gateway JWT authorizer passes the access token's `cognito:groups` claim into the Lambda event. The handler:

1. Parses `override: true` from the request body (default `false`).
2. If `override` is true, verifies that `budget-admin-{STAGE}` is in `cognito:groups`. If not, returns `403`.
3. If verified, skips the editability check on this request only.
4. For budget-target writes (`/replace` and `/pin`), sets `override: true` on every audit entry the request writes.

Hard delete (`DELETE /api/categories/{id}`) uses the same group claim but does not use the `override` flag — the operation is admin-only regardless. See **Hard delete semantics**.

The operational/UX side of admin mode (bootstrap, frontend toggle, per-action behavior, admin tools page) is documented in **Admin Operating Model** below.

### Audit scope

Recorded in `BudgetAuditLog-{stage}`:

- `POST /api/budget/{YYYY-MM}/replace` → per-category `CREATE` or `UPDATE` entries. `/replace` cannot legitimately remove a row (replace-all requires every existing row in the body), so it never produces `DELETE` entries. Budget row deletions happen through three other paths and are logged differently: `/pin` with `amount: null` writes an `UNPIN` entry per cleared pin; deactivation that drops future pins writes an `UNPIN` entry per drop; hard delete cascades through every row for the category and writes a single `CATEGORY_HARD_DELETE` entry.
- `POST /api/budget/{YYYY-MM}/pin` → per-category `PIN` or `UNPIN` entries.
- `POST /api/categories/{id}/deactivate` when `confirm: true` and `affectedMonths` is non-empty → one `UNPIN` entry per dropped pin. This keeps the budget-target audit log complete even when pins are dropped indirectly. The deactivation itself produces no entry.
- `DELETE /api/categories/{id}` → a single `CATEGORY_HARD_DELETE` entry. This is an exception to the "category lifecycle is not audited" rule because hard delete is irreversible and destroys historical data; the entry is the only remaining trace of the category and the action.

### Audit entry `changes` payload

The `changes` field on a `BudgetAuditLog-{stage}` row is action-shaped:

- `CREATE` (a new Budget row was written via `/replace`): `{amount: {before: null, after: number | null}}`.
- `UPDATE` (an existing Budget row's amount was changed via `/replace`): `{amount: {before: number | null, after: number | null}}`.
- `PIN` (a future pin was written via `/pin`, either new or replacing an existing pin): `{amount: {before: number | null, after: number}}` where `before` is `null` if there was no prior pin at this `(yearMonth, categoryId)`.
- `UNPIN` (a future pin was cleared, either via `/pin` with `amount: null` or via deactivation dropping pins): `{amount: {before: number, after: null}}`.
- `CATEGORY_HARD_DELETE`: `{budgetRowsDeleted: number, transactionsDeleted: number, name: string}` (a flat counts/snapshot payload, not a before/after diff — the category and its data no longer exist).

### Audit entry `override` field

The `override` boolean indicates the entry was produced by an action that required admin privileges. Specifically: `override=true` when (a) the request was submitted with `"override": true` and the JWT carried the admin group claim, or (b) the action is intrinsically admin-only and has no override flag — `CATEGORY_HARD_DELETE` is the only case in this category. `override=false` for all routine, non-admin mutations. The Audit Log page surfaces this flag prominently so audit reviewers can filter to "everything that required admin."

### Audit user identity

Each entry stores the actor as a nested object:

```
user: {
  sub: "<cognito-user-sub-uuid>",   // immutable; the canonical identifier
  email: "user@example.com",         // at-time-of-action snapshot
  username: "user@example.com"       // at-time-of-action snapshot (Cognito username, often = email)
}
```

All three fields are read from the JWT claims at request time (`sub`, `email`, `cognito:username`) and written verbatim into the entry. The snapshot semantics matter: if the user later changes their email or Cognito username, the audit log still shows whatever value was in effect when the action was performed. This matches the historical-record nature of the log. `sub` is the only field guaranteed to identify the same human across changes; the other two are intentionally allowed to drift on the live user record.

The Audit Log page renders entries using `email` as the primary display label (with a hover/tooltip showing the `sub` and `username` for disambiguation if needed).

Not recorded:

- Transaction mutations (insert/update/delete/commit), even when performed via override. The accepted trade-off: an override-driven edit to a transaction in a locked month leaves no direct audit trail. This is acceptable because (a) budget-target history is the primary need, and (b) the locked-month summary still reflects the new transaction state, so override-driven mutations are visible by inspection of the historical view itself.
- Category creation, renames, and reactivation. Each of these can be undone or re-derived from the current Category row, so a direct audit entry offers little forensic value.
- Deactivation as such — there is no "category was deactivated" entry. (Deactivation does, however, produce one `UNPIN` entry per dropped pin, as noted above; those entries cover the *budget-target* changes triggered indirectly. The deactivation itself remains uncaptured.)

### Historical fidelity

A year-month becomes locked once its grace period expires. The Budget table rows and Transactions table rows for a locked year-month are immutable except via admin override; the override path is audited. The summary endpoint for a locked month therefore reads the same values 20 years from now as it did the day the month locked, with the audit log explaining any override-driven divergences.

The summary endpoint determines which categories to include per **Spec 5**:

- **Editable year-months** — currently active categories, plus any category (active or inactive) referenced by at least one transaction with `amount != 0` in that month. Per the signed-amount convention, this includes pure-income/return-only categories (sum-of-amounts negative) as well as expense categories — anything with non-zero financial activity.
- **Locked year-months** — every category referenced by a budget row (regardless of amount; `$0` counts as a target, missing row means no target) or a transaction in that month, regardless of current `active` flag. Because past budget rows are never deleted when a category is deactivated, presence of a row in the Budget table for that month is the historical signal — no separate snapshot is needed.

### Display names on locked months

For locked-month summary responses, the category name returned for each row is resolved against `Category.nameHistory`:

1. Compute `month_end_utc` = the instant 23:59:59.999999 on the last calendar day of the requested year-month in `BUDGET_TZ`, converted to UTC. (Example: for `2024-03`, this is `2024-03-31T23:59:59.999999-04:00` (EDT) → `2024-04-01T03:59:59.999999Z`.)
2. Find the earliest entry in `nameHistory` whose `replacedAt` (ISO-8601 UTC) is **strictly greater than** `month_end_utc`.
3. If such an entry exists, that entry's `previousName` was the name in effect during that month; return it as `historicalName` alongside the current `name`. The frontend renders the pair as e.g. `Groceries (renamed to: Food)`.
4. If no such entry exists, the current `name` was already in effect during that month; return only `name` with `historicalName: null`.

The DST-aware conversion in step 1 matters at month boundaries near DST transitions — the cutoff has to use the offset in effect on the last day of the year-month, not a fixed offset.

Editable-month responses always return only the current `name` since no rename can have post-dated an editable month while it remains editable.

### Replace write semantics

`POST /api/budget/{YYYY-MM}/replace` writes a dense year-month (the current month, the previous month while in grace, or — via admin override — any locked month). Body:

```
{
  "rows": [{ "categoryId", "amount": number | null }, ...],
  "explanation": "...",
  "override": false
}
```

Replace-all semantics. The handler validates in this order:

1. **Editability** (per **Enforcement** table). If `{YYYY-MM}` is not writable (and no effective override), the handler returns `409` with the editability error and stops — body validation is not run.
2. **Body completeness:**
   - Every category referenced by any existing budget row for that month must be present in the body, even if its amount is unchanged.
   - Every category referenced by a non-zero transaction in that month must be present in the body.

If either body-completeness constraint is violated (and editability passed), the response is `409 Conflict` with a body listing the missing `categoryId`s, and **no rows are written**. The client is expected to re-issue with the missing entries included (typically copying their existing values).

`amount: number` → row is written with that amount (including `0`, which is a valid explicit target).
`amount: null` → row is written with `amount=null` (semantically "no target"; the row stays in the table to preserve density).

Every diff produces a per-category `CREATE` or `UPDATE` entry in the audit log. `/replace` never produces `DELETE` entries: the body validation rule prevents row removal by omission, and rows whose amount becomes `null` are still kept as rows (so they UPDATE, they don't DELETE).

### Pin write semantics

`POST /api/budget/{YYYY-MM}/pin` writes one or more explicit pins on a future editable year-month. Body:

```
{
  "rows": [{ "categoryId", "amount": number | null }, ...],
  "explanation": "...",
  "override": false
}
```

Upsert semantics — categories omitted from the body are not touched.

`amount: number` → upserts an explicit pin row at the given amount.
`amount: null` → **deletes** the pin row if it exists (no row at all means "no pin," and display falls back to walk-back).

The response includes warning payloads per category:

```
{
  "rows": [{ "categoryId", "amount", "stored": "PINNED" | "UNPINNED" }, ...],
  "warnings": {
    "downstreamPins": [
      { "categoryId", "yearMonth", "amount" }
    ],
    "pinMatchesCarriedValue": [
      { "categoryId", "amount" }
    ]
  }
}
```

- **downstreamPins** — for each category in the request, lists other pins for the same category in months strictly later than the edited month (within the editable window). The frontend surfaces these so the user can clear them in a follow-up call if desired. (Spec 19.)
- **pinMatchesCarriedValue** — for each category where the new pin amount equals the value that would have been resolved via walk-back without the pin. The frontend warns the user that they're effectively pinning the current carried value, which will block propagation. (Spec 20.)

Every pin/unpin produces a `PIN` or `UNPIN` entry in the audit log.

## Carry-Forward

### Storage model: dense vs. sparse

The Budget table holds **explicit edits and densified rows only**:

- **Locked, grace, and current year-months are always *dense*** — they contain exactly one row per category that existed at densification time, plus any explicit edits made after. A row may carry `amount=null` (explicit "no target"); the row's existence is what matters for density.
- **Future year-months are *sparse*** — they contain only rows the user has explicitly pinned via `POST /api/budget/{YYYY-MM}/pin`. Categories without a pin have no row at all.

This split has three consequences worth stating explicitly:

1. **Locked-month displays never walk back.** The dense row set written during the month's densification (whether by the scheduled cron at rollover or by lazy walk-forward later) is the historical record. Edits to prior locked months via admin override cannot retroactively change the display of a later locked month.
2. **Future-month edits are surgical.** Setting `December 2026 ABC = $2000` writes one row. `DEF` does not get a row in December until either (a) the user pins it explicitly or (b) December rolls over and is densified.
3. **Display of a future month is resolved per category.** For each currently-active category: if there's an explicit pin at `(future_ym, category)`, use it. Otherwise walk back month-by-month (no fixed depth — sweep until you find a row or exhaust history) and use the most recent row's amount. If nothing is ever found, the category has no target.

### Densification

Densification is the act of converting the current year-month from sparse to dense. It runs in two places:

**Scheduled (eager).** EventBridge Scheduler triggers a Lambda at `0 0 1 * ? *` with `ScheduleExpressionTimezone: "America/New_York"` (i.e., midnight ET on day 1 of each month). The job is idempotent; running it twice is a no-op.

**Lazy (fallback).** If the scheduled job hasn't yet run for a year-month (or failed, or the user accesses the system after a long absence), densification runs inline on the next budget-related request. The triggers are: any `GET /api/budget/{yearMonth}` (regardless of which yearMonth is requested), any `GET /api/summary?month={yearMonth}`, or any budget write (`/replace`, `/pin`, `POST /api/categories`). The handler always brings the table up to the current `current_ym` before serving the request — even if the caller asked for a past or future month, current must be dense first so walk-back resolution and walk-forward bookkeeping stay correct. If lazy hydration runs during a request, the request waits for it to finish before returning.

### Walk-forward through missed months

When densification runs, it computes the set of year-months between `M_last` (the most recent already-dense year-month) and `current_ym` (the year-month containing now-ET). For each `M` in that range, in chronological order:

1. For each currently-active category:
   - If `(M, categoryId)` already has a row (an explicit pin written earlier), skip.
   - Otherwise, walk back from `M - 1` through `M_last` looking for the most recent row for that `categoryId`. Copy its `amount` (which may be `null`).
   - If no prior row exists anywhere, write a row with `amount=null`.
2. Inactive categories are not added. Explicit pins on inactive categories that already exist at `M` are left in place (the user may re-activate or just want to track them historically).

**Cold-start case (no prior dense month exists).** When `M_last` is undefined — the Budget table has zero rows — densification has nothing to walk back to. In that case, only `current_ym` is densified: for each currently-active category, write a row with `amount=0`. This should virtually never happen in normal operation (a fresh deploy with categories already created, before any user has loaded a budget page). If it does happen for any other reason, `$0` is a safe starting baseline that the user can edit normally.

Iterating forward (rather than collapsing to one walk-back from `current_ym`) ensures intermediate months become dense in their own right, which preserves historical fidelity if any of them later get inspected as a locked month.

**Implementation note — bulk-fetch the lookback window.** Both densification and future-month display walk back through Budget rows category-by-category, month-by-month. Implemented naively this is `O(categories × months)` round-trips. The handler should instead issue one `BatchGetItem` (or a small number of `Query`s on the relevant `yearMonth` partitions) up front to load the entire `[M_last, current_ym + N_FUTURE_MONTHS]` window into a Python `dict[(yearMonth, categoryId), amount]`, then resolve every walk-back via in-memory lookups. This applies equally to:

- Densification at rollover (walking back from each `M` looking for prior rows).
- `GET /api/budget/{future_ym}` and `GET /api/summary?month={future_ym}` (walking back per active category to compute effective targets).

### Category lifecycle hooks

- **Create** (`POST /api/categories`) — body must include a non-zero, non-negative `initialTarget`. The handler first triggers lazy hydration if `current_ym` is not yet dense, then writes a row at `(current_ym, newCategoryId, initialTarget)` so the new category appears in Spec-1-style summaries right away. The new category's row participates in any subsequent walk-back for future months (so a freshly-created category with `initialTarget=$50` will show `$50` as the carried value for all future editable months until the user pins something different).
- **Deactivate** (`POST /api/categories/{id}/deactivate`) — returns `affectedMonths: [{yearMonth, amount}]` listing every **future** month with an explicit pin for this category. With `confirm: true`, the deactivation transaction batch-deletes those future pins AND writes one `UNPIN` audit entry per dropped pin (preserving the budget-target audit trail; see **Audit scope**). Past dense rows (current/grace/locked) are left alone, preserving Spec 2's historical fidelity.
- **Reactivate** (`POST /api/categories/{id}/reactivate`) — flips the flag. Future pins dropped during the prior deactivation are not restored. The category re-enters the active set, so the next densification (or any current-month write) treats it like a freshly-created one for that month.

### Edge cases

- **New category, no prior history.** Densification finds no row to walk back to and writes `amount=null`. The category appears in the current month with no target; the user must explicitly set one.
- **Pin equals carried value.** Allowed but warned (see Pin write semantics, `pinMatchesCarriedValue`). Server writes the pin as requested.
- **Pin survives rollover.** When a pinned future month becomes current, densification finds the explicit pin already in place and skips it. The pin becomes a regular dense row going forward.
- **Pin on a category that gets deactivated before the future month arrives.** Per the deactivate flow above, the pin is deleted at deactivation time. If the user skipped the confirm prompt somehow (e.g., direct API call) and the pin survives, densification at the future month's rollover ignores it (inactive categories aren't densified). While the month is editable, the orphan pin is invisible to summary views (Spec 5 editable-month rule shows only active categories + categories with transactions). Once that month locks, Spec 5's locked-month rule applies and the orphan budget row resurfaces in the summary with `$0` actuals. To remove it for good, either reactivate the category and follow the normal deactivate flow, or hard-delete the category.
- **Concurrent edits across tabs.** Last write wins. No ETag/version checking. Acceptable for single-household use.

## Hard delete semantics

`DELETE /api/categories/{id}` is semantically distinct from deactivation and is the only category-lifecycle operation that is destructive, irreversible, and audited. It exists for the case where a category was created in error and should not exist in any historical record — not for the case of "I no longer want to budget this," which is what deactivation is for.

### Access

Admin-only. The handler verifies the `budget-admin-{stage}` claim on every call. There is no `override` flag — admin status alone is required.

The frontend does not surface hard delete on the standard `CategoriesPage`. It lives behind a separate admin tools route that is only rendered when the JWT carries the `budget-admin-{stage}` claim.

### Pre-flight (dry run)

`GET /api/categories/{id}?deletion_preview=true` returns the impact summary without making any changes:

```
{
  "categoryId": "01HQ...",
  "name": "Coffee",
  "impact": {
    "budgetRows": 47,        // total Budget rows referencing this category
    "transactions": 312,     // total Transactions referencing this category
    "lockedMonthsAffected": 18,
    "auditEntriesReferencing": 89  // not deleted, but will become unresolvable
  }
}
```

The admin tools UI requires the admin to view this preview before the destructive call is allowed.

### Destructive call

```
DELETE /api/categories/{id}
Body: {
  "confirm": true,
  "confirmName": "Coffee",       // must match Category.name exactly, case-sensitive
  "explanation": "..."           // required, non-empty
}
```

Handler behavior:

1. Verify `budget-admin-{stage}` claim. Else `403`.
2. Verify `confirm=true`, `confirmName` matches the current `Category.name`, and `explanation` is non-empty. Else `400`.
3. In a single conceptual operation:
   a. Scan-and-delete every Budget row with `categoryId = id` across all year-months.
   b. Scan-and-delete every Transaction row with `categoryId = id` across all year-months.
   c. Delete the Category row.
   d. Write one `CATEGORY_HARD_DELETE` audit entry into the single-partition audit table: `PK="AUDIT"`, `sortId=<new ULID>`, `changedAt` set to now in UTC, `effectiveYearMonth=null`, `categoryId=id`, `explanation`, `user={sub, email, username}`, `override=true` (per the "intrinsically admin-only" rule in **Audit entry `override` field**), `changes={budgetRowsDeleted: N, transactionsDeleted: M, name: previousName}`.
4. Return `200` with the deletion counts.

DynamoDB does not provide cross-table atomicity here; the operation is best-effort sequential. If any sub-step fails after others succeeded, the audit entry is written last so its presence implies (modulo manual intervention) the cascade completed. If the audit entry write fails, the admin is notified and the partial state must be reconciled manually.

### Effects on history

Hard delete intentionally violates Spec 2 for the deleted category:

- **Locked-month summaries** that previously included this category will no longer include it. Total actuals for those months will decrease by the deleted transactions' amounts. This is by design — the admin has stated the category should never have existed.
- **Audit log entries** that referenced the deleted `categoryId` (e.g., a past `CREATE`/`UPDATE`/`PIN` entry on that category) are not deleted. The category name will not resolve, so the UI renders them as `<deleted category {id}>` with a tooltip showing the original `Category.name` from the `CATEGORY_HARD_DELETE` audit entry's `changes.name` field.
- **Transactions in locked months** are deleted; this is the most aggressive part of the cascade and the main reason hard delete is reserved for "this category never should have existed."

### Why not orphan transactions instead?

We considered orphaning — setting `categoryId = null` on Transactions rather than deleting them — but rejected it because (a) it creates a null-category state the rest of the system has to defend against (summary aggregation, replace-all validation, etc.), and (b) it doesn't actually serve the use case. If the admin wants to keep the transactions but recategorize them, they should reassign each one to a real category first, then hard-delete an empty category. The current design forces that explicit step.

## Admin Operating Model

This section covers the end-to-end experience of operating as admin: how admins are provisioned, how they enter admin mode in the frontend, what each mutation type looks like under admin mode, and what the admin tools page contains. The API contract for the `override` flag and the JWT claim is in **Editability and the Admin Override > Admin override** above.

### Bootstrap

CDK creates the `budget-admin-{stage}` Cognito group as part of `PlatformStack` (or wherever the user pool lives). The group is **empty after deploy**. The deploy operator adds themselves (or anyone else who needs admin) via:

```
aws cognito-idp admin-add-user-to-group \
  --user-pool-id <pool-id> \
  --username <email> \
  --group-name budget-admin-{stage}
```

The added user must sign out and sign back in so their new JWT carries the `cognito:groups` claim. There is no in-app UI for granting or revoking admin status — adding admins is rare enough that AWS CLI is the right surface forever.

### Session model

A toggle in the app header is rendered **only when the JWT carries `budget-admin-{stage}`**. Two states: Off (default) and On.

- **Defaults to Off** on every page load, every new tab, every sign-in. State is **per-tab**, held in `useState` only — never persisted to `localStorage`, `sessionStorage`, or cookies.
- **No inactivity timeout.** The state persists until the user toggles it off, closes the tab, or refreshes. The visual treatment (below) is the safety mechanism.
- Toggling between Off and On is one click in either direction; no re-authentication, no confirm dialog. The friction lives at the per-action layer.

### Visual treatment

When admin mode is On:

- A persistent banner spans the top of the viewport: `Admin mode active — your changes can bypass lock and grace rules. [Turn off]`.
- The banner uses an alarm color (amber or red).
- The header / nav strip is tinted the same color so admin mode is unmissable on every page.
- An **Admin tools** item appears in the navigation.

When Off, no banner, no tinted header, no admin tools nav entry.

The banner and tint are the sole safeguard against "I forgot it was on." They are intentionally aggressive.

### Per-action behavior under admin mode

For each mutation type, this section documents (a) what the UI shows when admin mode is Off (the lock blocks the action), (b) what it shows when admin mode is On (the action is unblocked), and (c) whether an explanation is collected.

| Action | Off (locked context) | On (admin mode) | Explanation collected |
|--------|---------------------|-----------------|----------------------|
| `POST /api/budget/{YYYY-MM}/replace` on a locked month | Form is read-only; no Save button. | Form is editable. Save button reads "Save with override". | Yes — same `explanation` field the form requires for every `/replace`, written to the audit log with `override=true`. |
| `POST /api/budget/{YYYY-MM}/pin` on a locked month | Pin controls hidden. | Pin controls visible. Save button reads "Save with override". | Yes — same `explanation` field, written to the audit log with `override=true`. |
| `POST /api/transactions` with date in locked month | "Save" disabled with tooltip explaining lock. | "Save" enabled, label reads "Save (override)". | No — transactions are not audited; no explanation field is shown. |
| `POST /api/transactions/update` moving a row into/out of a locked month | "Save" disabled. | "Save" enabled, label reads "Save (override)". | No. |
| `POST /api/transactions/delete` on a row in a locked month | "Delete" disabled. | "Delete" enabled, label reads "Delete (override)". | No. |
| `POST /api/transactions/commit` with any locked-month rows | Locked rows surface as inline errors; Commit button disabled. | Locked rows become inline warnings (different color). A persistent header on the review screen reads: "Committing N rows in locked months: [Mar 2024, Apr 2024] via admin override." Commit button reads "Commit (override)". | No. |
| `DELETE /api/categories/{id}` | Not reachable from any page. | Reachable only via Admin tools. Form on its own page; not gated by the session toggle. | Yes — typed-name confirmation + required explanation, written to the `CATEGORY_HARD_DELETE` audit entry. |

The asymmetry between budget targets (explanation collected) and transactions (no explanation) is a direct consequence of the audit scope decision: there's no point asking the user to type a justification that is then discarded.

### Admin tools page

Lives at `/admin`, rendered only when the JWT carries `budget-admin-{stage}`. Visiting `/admin` does **not** require the session toggle to be On — admin tools always have their own per-action safeguards (see **Hard delete semantics**).

Initial contents:

- **Hard delete category.** Dropdown of all categories (active + inactive). On select, fetches `GET /api/categories/{id}?deletion_preview=true` and displays the impact counts. Typed-name confirmation field + explanation field + red "Permanently delete" button.

Reserved space for future tools (not in v1):

- Manual carry-forward trigger (force-run densification of the current month).
- Cron health (timestamp of last successful scheduled densification).
- Raw audit log query (filter by user, date range, action).

### Stage isolation

A user added to `budget-admin-dev` has admin access in dev only. To grant admin access in prod, the same user must be added to `budget-admin-prod` separately. This is enforced server-side: the Lambda reads its `STAGE` env var on every request and rejects override / hard-delete attempts where the JWT does not carry the stage-specific group.

The frontend computes the same group name from a stage value injected at build time (via the existing `config.json` deploy mechanism), so the admin toggle and `/admin` route appear only when the user has the right stage-specific claim.

## LLM-Driven CSV Import (`budget/csv_import.py`)

Two Anthropic API calls per upload, both reading the API key from SSM (`/budget/{stage}/anthropic-api-key`):

1. **Column mapping** — given the CSV headers and ~5 sample rows, identify which columns are `date`, `description`, `amount`, and whether amounts need to be inverted (some statements use negative for purchases).
2. **Categorization** — given all transaction descriptions and the user's active categories, assign each one to the most appropriate category.

The upload endpoint returns the parsed + categorized rows for the user to review and edit before committing.

### Upload response shape

`POST /api/transactions/upload` returns each parsed row alongside per-row validation annotations so the review UI can surface problems before the user clicks Commit:

```
{
  "rows": [
    {
      "transactionDate": "2024-03-15",
      "description": "...",
      "amount": 12340000,
      "categoryId": "01HQ...",         // null if LLM could not assign
      "validation": {
        "editability": "EDITABLE" | "GRACE" | "LOCKED",
        "issues": ["missing_category", "locked_month"]
      }
    },
    ...
  ]
}
```

The `issues` array is a closed set:

- `missing_category` — the LLM did not assign a `categoryId` (or assigned one that doesn't match an existing category). The user must pick one inline.
- `locked_month` — the row's `transactionDate` year-month is `LOCKED` per the editability state function. The user must change the date or enable admin override.

No other issue strings are emitted by this endpoint. Parsing-level failures (malformed date, unparseable amount) cause the upload itself to fail before producing per-row results, with a top-level error describing the bad row(s).

The client renders rows with non-empty `issues` as blocked until the user fixes them inline (e.g. picking a category, adjusting the date) or enables admin override. Commit is unreachable from the UI until either every row is valid or override is on.

### CSV commit semantics

Commit is atomic at the API level via `POST /api/transactions/commit`, which accepts the reviewed batch as a single request:

```
POST /api/transactions/commit
Body: {
    "rows": [{ "transactionDate", "description", "amount", "categoryId" }, ...],
    "override": false
}
```

Handler behavior:

1. Compute `editability(row.transactionDate.yearMonth, now)` for every row.
2. If any row is LOCKED and `override` is not effective (either not requested or the JWT lacks `budget-admin-{stage}`), the response is `409 Conflict` with a per-row error report and **zero rows are written**.
3. If every row passes (or override is effective), insert all rows. The Transactions table writes are batched via DynamoDB `BatchWriteItem`. If a partial-write retry is exhausted, the request returns `500`. **Retry is not idempotent**: each request generates fresh ULIDs, so a client retry after a `500` may duplicate rows that the prior attempt actually persisted before the failure. This is an accepted trade-off in exchange for the simpler server design; users who hit this rare failure mode must inspect the ledger and clean up duplicates manually (potentially via admin override on locked months).

The previous per-row `POST /api/transactions` path remains for single-transaction inserts from the UI but is not the CSV commit path.

## Environment Variables

### Budget Handler Lambda

```
+-----------------------------+-----------------------------------+
| Variable                    | Purpose                           |
+-----------------------------+-----------------------------------+
| CATEGORY_TABLE_NAME         | DynamoDB Category table           |
| BUDGET_TABLE_NAME           | DynamoDB Budget table             |
| TRANSACTIONS_TABLE_NAME     | DynamoDB Transactions table       |
| BUDGET_AUDIT_LOG_TABLE_NAME | DynamoDB audit log table          |
| SSM_API_KEY_PARAM           | SSM path to the Anthropic API key |
+-----------------------------+-----------------------------------+
```

All env vars are accessed via `get_env_var()` which raises if missing or blank.

## Frontend (`budget/`)

React + TypeScript via Vite. Pages: `BudgetPage`, `TransactionsPage`, `CategoriesPage`, `SummaryPage`, `UploadPage`, `AuditLogPage`, `AdminToolsPage`, `CallbackPage`. Shared infrastructure: `auth.ts` (PKCE flow, single-flight refresh dedupe), `api.ts` (typed wrappers), `MonthPicker`, `LoadingOverlay`, `StatusMessage`, `DevBanner`, `AdminBanner` (the persistent banner shown when admin mode is on). Built artifacts in `budget/dist/` are deployed by the CDK stack's `BucketDeployment`, which also injects a `config.json` containing the Cognito domain, client ID, and stage at deploy time so the same bundle works across stages — the stage value is what lets the frontend compute the expected `budget-admin-{stage}` group name.

### Pinned-row indicator

For any year-month past the current one, summary and budget rows include a `pinned: bool` flag from the server. The frontend renders pinned rows with a distinct visual treatment (e.g. a colored dot or chip with the text "pinned") so the user can immediately see which targets are sticky vs. carried-forward (Spec 17). Once a pinned year-month rolls into current/grace/locked, the pin flag is dropped on the response — the row becomes an ordinary dense row at that point and the original pin metadata is not surfaced.

When the user submits a pin edit, the server's response includes `warnings.downstreamPins` and `warnings.pinMatchesCarriedValue`; the UI shows a dialog summarizing these and offering "Keep pins" / "Clear downstream pins" buttons before confirming the edit was successful.

### Audit log page

`AuditLogPage` calls `GET /api/audit-log?limit=N` where `N` is configurable in the UI (default `10`, server cap `200`). Renders the most recent entries with per-entry `override` flag visible.

## Testing

Python unit tests live in `lambda/tests/`. Budget-specific files: `test_budget_handler.py`, `test_budget_categories.py`, `test_budget_budget.py`, `test_budget_transactions.py`, `test_budget_summary.py`, `test_budget_audit.py`, `test_budget_csv_import.py`. All DynamoDB and Anthropic calls are mocked. Run with `uv run pytest` from `lambda/`.

CDK tests live in `infra/test/`. Run with `npm test` from `infra/`.

## Key Design Decisions

- **Two stacks** — DynamoDB separate from the web stack so data survives app redeploys and the prod removal policy can be `RETAIN` without coupling it to the Lambda lifecycle.
- **Amounts as integer millionths** — full precision, no floating-point drift.
- **ULID identifiers** — sortable by creation time, opaque to URLs, no coordination needed.
- **Sparse futures, dense current/past** — explicit pins are the only Budget rows that exist for future months; dense rows are written by densification at rollover (eager cron + lazy fallback). This keeps the future "live" (responsive to changes in prior months) while making locked months self-contained historical records that don't require walking back at display time.
- **POST for all mutations, except hard delete** — `POST` for budget writes (`/replace`, `/pin`) and transaction writes keeps bodies intact through CloudFront and provides a uniform request shape. Hard delete on a category keeps the `DELETE` verb deliberately — its destructive, admin-only semantics deserve the verb that signals danger, even though it diverges from the convention used everywhere else.
- **CloudFront-proxied OAuth** — Cognito hosted UI served on the app's origin so refresh requests are same-origin (no CORS).
- **PKCE auth flow** — no client secret in the browser; tokens refreshed with deduplication on 401.
- **LLM column mapping** — handles arbitrary bank CSV formats without per-bank parsers.
- **Mandatory explanation on budget edits** — every change writes audit entries with a human-readable reason.
- **Deactivate preserves history; hard delete destroys it** — these are intentionally distinct semantic operations, not two flavors of the same thing. Deactivate is the normal "I no longer want to budget this" path, preserves every Budget row and Transaction, drops future pins on confirmation, and is reversible. Hard delete is the "this category should never have existed" admin operation that cascade-deletes every Budget row and Transaction across all year-months including locked ones, writes a `CATEGORY_HARD_DELETE` audit entry, and explicitly breaks Spec 2 for the deleted category. Hard delete is gated by the `budget-admin-{stage}` group claim, requires a typed name confirmation, and lives behind an admin tools route — it is not reachable from the normal categories page.
- **Server-computed editability** — the lock/grace state is derived from ET on every mutating request, so the client can never trick the backend into editing a locked month. The `budget-admin-{stage}` group claim is the only path that grants override, and the override flag itself is meaningless without that claim.
- **Stage-isolated admin groups** — `budget-admin-dev` and `budget-admin-prod` are separate Cognito groups, so dev admin status cannot leak into prod even for the same human user. Deliberate friction; explicit per-stage group assignment is required.
- **Atomic CSV commit (pre-flight only)** — the commit endpoint validates the whole batch before writing any row, so locked-month rows never sneak in. However, a partial-write failure mid-commit leaves the ledger in a partially-applied state and a client retry may dupe rows; this is the chosen trade-off vs. building deterministic batch IDs.
- **Budget-targets-only audit log** — transaction mutations are not audited, which keeps the schema simple and matches the user's actual review workflow (historical correctness of *budget vs. actual* is the primary signal, not transaction-edit forensics).
- **Category name history** — renames are always allowed and append to a `nameHistory` list on the category row, letting locked-month views resolve the name in effect at the time without snapshotting names onto every Budget/Transaction row.
