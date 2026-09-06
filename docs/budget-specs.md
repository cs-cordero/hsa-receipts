# Specs - Family Budget App

## Definitions

- **Current year-month** — the year-month that holds "now" in US/Eastern. The budget always uses
  ET, wherever the user is.
- **N** — the number of future year-months that the user can see and can budget, counted from the
  current year-month.
- **Grace period** — a period after a year-month ends, in which the year-month stays editable. At
  the end of the grace period, the year-month becomes **locked**.
- **Editable year-month** — the current year-month, the previous year-month while its grace period
  continues, or any of the next N year-months.
- **Locked year-month** — any year-month that is not editable.
- **Override** — a way for the user to act on a locked year-month. The server must enforce the
  override. It is not enough to hide the action in the UI.

## Budget Summary

1. I want a page with a table that summarizes the current budget. Spec 5 defines which categories
   the table shows. Each row shows the category, its budgeted amount for the year-month, and the
   actual expenditures for the year-month.
2. I want to see any previous year-month as it was at the end of its grace period. A locked
   year-month must look the same in 20 years as it looked on the day it locked. A budget change
   made later through the override is an exception, and the audit log must show it. The app does
   not audit a transaction change made through the override — see Spec 9 for that trade-off.
3. I want to see the next N year-months. The actual expenditures are usually empty for those
   months, but the budgeted amounts must be visible.
4. The next month becomes the current year-month when the US/Eastern clock goes past midnight on
   the first day. The previous year-month stays editable for a grace period of 7 days. It then
   locks. After that, the app rejects a change to its budget targets or to its transactions,
   unless I use the override.
5. The categories on the summary table are the superset of these:
   - For an editable year-month: the categories that are active now, and any category with
     expenditures other than zero in that month.
   - For a locked year-month: every category that had a budget target, or any expenditures in that
     month. "Had a target" means a recorded amount, and `$0` counts; `null` means no target. This
     applies even if the category is not active today. A deactivated category stays on a past
     month, so the historical view stays true.

## Transaction Ledger

6. I want to report transactions to the ledger. The app adds these together to make the actual
   expenditure values on the Budget Summary page.
7. I want these columns in the ledger: transaction date, description, budget category, amount.
8. The app must reject an insert, an update, or a delete of a transaction whose date falls in a
   locked year-month, unless I use the override. A transaction with a future date is permitted
   only if its date falls in an editable year-month — the current one, the next N, or the previous
   one in grace.
9. I want to upload a CSV of transactions. The app must use a low-cost LLM to map the columns, and
   to give a category to each row from my active categories. After the upload, I want an editable
   table of the parsed rows and their categories, with a Commit button. The review screen must show
   each broken rule beside its row — for example, a row dated in a locked month, or a category that
   is absent or unclear. The app must not wait until I click Commit to report them. The app must
   block Commit completely while any row is invalid, until I correct the rows or use the override.

## Budget Category

10. I want a page that shows all active budget categories, and a toggle to show the inactive ones
    as well.
11. I want to change the budgeted amount for each category in any editable year-month. The app must
    reject a change to the amount in a locked year-month, unless I use the override.
12. I can set a budget target only for an editable year-month — the previous one in grace, the
    current one, or any of the next N — unless I use the override.
13. I can rename a category at any time, whatever the lock state of any year-month. When a renamed
    category appears on a locked year-month, the app must show the rename — for example,
    `Groceries (renamed to: Food)`. I can then match what I see against a paper record from that
    time.
14. When I make a category, I must put it in a group (Spec 23). The first budget target is `$0` by
    default. That is a valid target, and it means "no spend planned this month". I can give a
    different amount instead, but it must not be negative. If the category is active, it must
    appear at once in the summary for the current year-month, with its first target.
15. Deactivation is the normal way to retire a category. It must be common and easy. It keeps every
    Budget row and every Transaction in the current, grace, and locked year-months, so the
    historical record stays whole (Spec 2). The app drops any future pinned amount for the category
    (Spec 18) when I confirm, as Spec 21 describes.
16. A hard delete is a different operation, and it destroys data. It removes the category for ever.
    It also deletes every Budget row and every Transaction that points at the category, in all
    year-months, including the locked ones. It breaks the historical fidelity of Spec 2 for that
    category on purpose. That is its point. Therefore:
    - Only an admin can do it. It stays out of the normal categories UI, and only an explicit admin
      tools page reaches it.
    - It needs a typed confirmation, such as the category name, and an explanation that the app
      records.
    - It is the only category operation that the audit log records, because no one can undo it.
    - Use deactivation for "I no longer want to budget this". Keep the hard delete for "this
      category should never have existed".

## Category Groups and Ordering

23. I want to put my categories into named **groups**, such as "Income", "Essentials", and
    "Discretionary". Every category belongs to exactly one group. No category is without a group.
24. Every category and every group has an explicit display order. On the Budget Summary and in the
    budget editor, the app sorts the categories first by the order of their group, and then by
    their position in that group. Each group shows as a section, with the group name in a header
    row above its categories.
25. I want to change the order of the groups, and the order of the categories in a group, by drag
    and drop on the Categories page. I also want to drag a category from one group to another. The
    app must keep the order and the moves between sessions.
26. I want to make a new group at any time. Each group name must be unique, and case does not
    count. The app puts a new group at the end of the order. I can then move it.
27. I can rename a group at any time. The new name shows everywhere the app draws the group name.
    Unlike a category rename (Spec 13), a group rename keeps no historical name. A group is
    organizational data only. It is not the historical record of where a transaction was budgeted.
28. I can delete a group when no **active** category points at it. On delete, the app moves any
    deactivated category in that group to the **Unassigned** group (Spec 30), so no category is
    left without a group. A group has no deactivation step. A group is organizational data only,
    and no transaction or budget row points at one, so the rule that protects a category does not
    apply. To delete a group is one click and one confirmation, and the group is then gone.
29. The app makes the "General" group on the first deploy. It is the home for any category that
    existed before. After that, it acts like any other group. I can rename it, move it, or delete
    it once I move its active categories somewhere else.
30. A permanent **Unassigned** group exists, and the app marks it as a system group. No one can
    rename it, delete it, or move it, and it always sorts last. It has one purpose: to hold a
    deactivated category whose group was deleted. The rule in Spec 23, that every category belongs
    to a group, therefore holds at all times. The frontend hides the Rename and Delete buttons for
    it, and shows a short note in their place.

## Carry-Forward and Future Pinning

17. When I look at a future year-month, the app derives the budgeted amounts. For each category
    that is active now, it shows the value I set most recently in any earlier year-month. A value
    that I **pin** for that category in that future year-month takes the place of the derived one.
18. I want to pin the budgeted amount of a category for any future editable year-month. A pinned
    amount must:
    - Stay in place when that year-month becomes the current year-month. The carry-forward must not
      write over it.
    - Stop an earlier change from moving past the pinned year-month. For example, I pin December at
      $2000, and I later change October to $1500. November then takes the $1500, but December stays
      at $2000.
    - Look different on the budget summary, such as with a coloured marker. I can then see at once
      which rows are pinned, and which rows carry forward.
19. When a change of mine conflicts with a pin further ahead, the app must warn me. It must show me
    which pins exist, and let me keep them or clear them.
20. When I pin a future year-month to the same value that the carry-forward would give, the app
    must warn me. I am then pinning the value that is there already, and that stops it from moving
    ahead later.
21. When I try to deactivate a category with future pinned amounts, the app must warn me and list
    them. If I confirm, the app drops the pins. The category then leaves nothing behind in a
    future year-month.

## Audit Log

22. I want a page that shows the most recent audit log entries for budget targets. The page must
    let me choose how many entries to get, and the default is the last 10. A hard delete of a
    category also appears in this log (Spec 16).

## Cross-cutting

- **Audit scope.** The audit log records every change to a budget target. This includes a pin, an
  unpin, and a pin that the app drops during a deactivation. It also records a hard delete of a
  category (Spec 16). It does not record an insert, an update, or a delete of a transaction, and
  this holds even through the override. The trade-off is that an override change to a transaction
  in a locked month leaves no direct trace. This is acceptable, because the budget rows keep the
  history at the level of the category.
- **Audit entries.** Each entry records the user, an explanation that a person can read, and
  whether the user used the override. A budget-target entry also records each changed field,
  before and after. A hard-delete entry records counts instead — how many rows the app destroyed —
  because the whole category is gone.
- **Override behavior.** The override is a privileged action. No one may get past the locked-month
  rules by a change to the client code, or by a skip of a UI toggle. The override applies only to
  a change. Any signed-in user may read without limit.
- **Notifications on bulk failures.** When the app rejects a batch, such as a CSV commit or a
  change across several months, one response must report every row and every month at fault. It
  must not report them one at a time.
