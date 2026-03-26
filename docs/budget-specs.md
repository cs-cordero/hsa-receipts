# Specs - Family Budget App

## Definitions

- **Current year-month** — the year-month containing "now" in US/Eastern. The budget lives in ET regardless of where the user physically is.
- **N** — the number of future year-months that can be viewed and budgeted from the current year-month.
- **Grace period** — a window after a year-month ends during which it remains editable. Once the grace period expires, the year-month is **locked**.
- **Editable year-month** — the current year-month, the previous year-month while still in its grace period, or any of the next N year-months.
- **Locked year-month** — any year-month that is not editable.
- **Override** — a mechanism that lets the user perform actions on locked year-months. Overrides must be enforceable on the server, not just hidden in the UI.

## Budget Summary

1. I want to be able to go to a page and see a table that summarizes the current budget. The set of categories shown is defined in Spec 5. Each row should show the category, its budgeted amount for the given year-month, and the actual expenditures for the given year-month.
2. I want to be able to view any previous year-month as it was at the moment its grace period ended. Looking at a locked year-month 20 years from now should show the same budgeted amounts and transactions it showed the day it locked. Budget edits made via override after lock are exceptions and must be visible in the audit log. (Transaction edits via override are not audited — see Spec 9 for the trade-off.)
3. I want to be able to view the next N year-months. Actual expenditures will usually be empty for those, but budgeted amounts should be visible.
4. When the clock in US/Eastern crosses midnight on the first of the next month, that month becomes the new current year-month. The previous year-month stays editable for a 7-day grace period. After grace expires it becomes locked: changes to its budget targets or its transactions are rejected unless I use the override.
5. The categories shown on the summary table should be the superset of:
   - For editable year-months: currently active categories, plus any category with non-zero expenditures in that month.
   - For locked year-months: every category that had a budget target (where "had a target" means a recorded amount, including `$0` — `null` means no target was set) or any expenditures in that month, regardless of whether it is active today. Deactivated categories continue to appear on past months so the historical view stays faithful.

## Transaction Ledger

6. I want to be able to report transactions to the ledger. This ledger gets aggregated up to the actual expenditures values on the Budget Summary page.
7. I want the ledger to include the following columns: transaction date, description, budget category, amount.
8. Inserting, updating, or deleting a transaction whose transaction date falls in a locked year-month should be rejected unless I use the override. Future-dated transactions are allowed only if their date falls within an editable year-month (current, next N, or previous-in-grace).
9. I want to be able to upload a CSV of transactions. The system should use a low-cost LLM to map columns and categorize each row against my active categories. After upload, I should see an editable table of the parsed/categorized rows with a Commit button. Any rule violations (e.g., row dated in a locked month, missing/ambiguous category) should be shown inline on that review screen — not first surfaced when I click Commit. Clicking Commit while any row is invalid should be blocked entirely until I fix the rows or use the override.

## Budget Category

10. I want a page where I can view all active budget categories, with a toggle to also show inactive ones.
11. I want to be able to edit the budgeted amount for each category in any editable year-month. Editing the amount in a locked year-month should be rejected unless I use the override.
12. I should only be able to set budget targets for editable year-months (previous in grace, current, or any of the next N), unless I use the override.
13. Renaming a category should be allowed at any time, regardless of any year-month's lock state. When a renamed category appears on a historical (locked) year-month view, it should display in a form that makes the rename visible — e.g. `Groceries (renamed to: Food)` — so I can match what I see on paper records from back then.
14. When I create a category, I must assign it to a group (Spec 23). The initial budget target defaults to `$0` (a valid explicit target meaning "no spend planned this month") but I can optionally provide a different non-negative amount. If the category is active, it should immediately appear in the current year-month's summary with its initial target.
15. Deactivating a category is the normal way to retire one and should be a common, low-friction action. It preserves every Budget row and Transaction in the current, grace, and locked year-months, so the historical record remains intact (Spec 2). Future pinned amounts for the category (Spec 18) are dropped on confirmation per Spec 21.
16. Hard-deleting a category is a fundamentally different, destructive operation. It permanently obliterates the category and cascade-deletes every Budget row and Transaction referencing it, across all year-months including locked ones. It intentionally violates historical fidelity (Spec 2) for that category — that is the point. As such:
    - It is admin-only, hidden from the normal categories UI, and only reachable from an explicit admin tools surface.
    - It requires a typed confirmation (e.g. typing the category name) and an explanation that gets recorded.
    - It is the only category-lifecycle operation that is recorded in the audit log, because it is irreversible and destructive.
    - Deactivation is the right action for "I no longer want to budget this." Hard delete is reserved for "this category should never have existed."

## Category Groups and Ordering

23. I want to organize my categories into named **groups** (e.g. "Income", "Essentials", "Discretionary"). Every category belongs to exactly one group — there are no orphan, ungrouped categories.
24. Every category and every group has an explicit display order. When I view the Budget Summary or the Budget editor, categories should be sorted first by their group's order, then by their position within the group. Each group should render as a section with the group name as a header row above its categories.
25. I want to be able to reorder groups and reorder categories within a group via drag-and-drop on the Categories page. I should also be able to drag a category from one group into another to move it. Reordering and moves should persist across sessions.
26. I want to create new groups at any time. Group names must be unique (case-insensitive). New groups are placed at the end of the group order; I can reorder afterwards.
27. Renaming a group should be allowed at any time. Renames affect every place the group name is rendered. Unlike category renames (Spec 13), group renames do not track historical names — groups are organizational metadata, not the historical record of where transactions were budgeted.
28. Deleting a group is allowed when no **active** category points at it. Deactivated categories in the group are auto-moved to the **Unassigned** sentinel (Spec 30) on delete so they aren't orphaned. There is no soft-delete / deactivation step for groups themselves: groups are purely organizational metadata (no transactions or budget rows reference them), so the historical-fidelity guard that protects categories doesn't apply. Group delete is one click + confirm = gone for good.
29. The "General" group is created automatically on first deploy and acts as the home for any pre-existing categories. After migration it behaves like any other group — I can rename it, reorder it, or delete it once I've moved its active categories elsewhere.
30. A permanent **Unassigned** group exists, marked as a system group. It cannot be renamed, deleted, or reordered, and always sorts at the bottom. Its sole purpose is to catch deactivated categories whose original group was deleted, so the "every category belongs to a group" invariant (Spec 23) is never violated by indirect means. The frontend hides Rename/Delete buttons for it and shows a small explanatory hint instead.

## Carry-Forward and Future Pinning

17. When I view a future year-month, the budgeted amounts I see are derived: for each currently active category, the value shown is whatever I most recently set in any prior year-month, unless I've explicitly **pinned** a value for that category in that future year-month.
18. I want to be able to pin a category's budgeted amount for any future editable year-month. Pinned amounts should:
    - Survive into that year-month becoming the current year-month at carry-forward, rather than being overwritten by whatever is then current.
    - Block further upstream edits from propagating past the pinned year-month — e.g., if I've pinned December at $2000 and later change October to $1500, November should pick up the $1500 but December stays at $2000.
    - Be visually distinct on the budget summary (e.g., a colored marker) so I can see at a glance which rows are pinned vs. carried-forward.
19. When I make an edit that conflicts with an existing downstream pin, the system should warn me, show me which pins exist, and let me choose to either keep them or clear them.
20. When I pin a future year-month to a value that happens to equal what would have been carried-forward anyway, the system should warn me that I'm effectively pinning the current value (which will block future propagation).
21. When I try to deactivate a category that has future pinned amounts, the system should warn me and list them. If I confirm the deactivation, the pins are dropped — the category leaves no trace in future year-months.

## Audit Log

22. I want to be able to view the most recent budget-target audit log entries on a page. The page should let me configure how many entries to fetch, with a default of the last 10. Hard-deletes of categories also appear in this log (Spec 16).

## Cross-cutting

- **Audit scope.** Mutations to budget targets are recorded in the audit log, including pin/unpin operations and pins dropped indirectly during deactivation. Hard deletes of categories are also recorded (Spec 16). Transaction inserts/updates/deletes (including those done via override) are not audited. The trade-off is that an override-driven edit to a transaction in a locked month is not directly traceable; this is acceptable because category-level history is preserved in the budget rows themselves.
- **Audit entries.** Each entry records the user, a human-readable explanation, and whether the override was used. Budget-target entries also record the changed field(s) (before/after). The hard-delete entry records a counts payload (how many rows were destroyed) instead of field diffs, since the whole category is gone.
- **Override behavior.** The override is a privileged action. It must not be possible to bypass locked-month rules by editing client code or skipping a UI toggle. The override only ever applies to mutations; reads are unrestricted to authenticated users.
- **Notifications on bulk failures.** When the system rejects a batch (CSV commit, multi-month edit, etc.), every offending row/month should be reported in one response, not one at a time.
