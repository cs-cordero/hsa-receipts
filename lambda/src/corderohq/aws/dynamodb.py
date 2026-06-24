"""AWS DynamoDB table classes for the budget app."""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from ulid import ULID

from corderohq.budget.editability import editability

_DYNAMO_RESOURCE = boto3.resource("dynamodb")
_LOGGER = logging.getLogger(__name__)
_BUDGET_TZ = ZoneInfo("America/New_York")


def current_year_month() -> str:
    """Return the current YYYY-MM string."""
    now = datetime.now(tz=UTC)
    return f"{now.year}-{now.month:02d}"


def _month_end_utc(year_month: str) -> datetime:
    """End-of-month instant for `year_month` in BUDGET_TZ, converted to UTC.

    Per the architecture's "Display names on locked months" section: the cutoff
    must use the DST offset in effect on the last day of the year-month, not a
    fixed one. ZoneInfo handles that automatically — we just construct the local
    end-of-month datetime and call .astimezone(UTC).
    """
    year, month = int(year_month[:4]), int(year_month[5:7])
    last_day = calendar.monthrange(year, month)[1]
    local_end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=_BUDGET_TZ)
    return local_end.astimezone(UTC)


def _prev_year_month(year_month: str) -> str:
    year, month = int(year_month[:4]), int(year_month[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _walk_back_amount(by_key: dict[tuple[str, str], Any], year_month: str, cat_id: str, max_steps: int = 240) -> Any:
    """Find the most recent stored amount at or before `year_month` for `cat_id`.

    Mirrors densify.walk_back_for but lives here to avoid a circular import
    between dynamodb.py and budget.densify (densify imports BudgetTable from
    here). Returns None if no row is found within the safety bound.
    """
    if (year_month, cat_id) in by_key:
        return by_key[(year_month, cat_id)]
    cursor = year_month
    for _ in range(max_steps):
        cursor = _prev_year_month(cursor)
        if (cursor, cat_id) in by_key:
            return by_key[(cursor, cat_id)]
    return None


def _resolve_historical_name(category: dict[str, Any], month_end_utc: datetime) -> str | None:
    """Return the category's `previousName` in effect during `month_end_utc`, or None.

    Walks `nameHistory` for the earliest entry whose `replacedAt` is strictly
    greater than `month_end_utc`. If found, the category was renamed AFTER the
    month being summarized — its previousName is the name at the time. Otherwise
    the current name was already in effect and we return None.
    """
    history = category.get("nameHistory") or []
    if not history:
        return None
    # Sort by replacedAt ascending so we pick the earliest entry post-dating the month.
    sorted_history = sorted(history, key=lambda e: e["replacedAt"])
    for entry in sorted_history:
        replaced_at = datetime.fromisoformat(entry["replacedAt"])
        if replaced_at > month_end_utc:
            return str(entry["previousName"])
    return None


class CategoryGroupTable:
    """CRUD operations for category groups.

    Groups own an `order` int — lower numbers display first. Reordering is
    coarse-grained (write the full new order via `reorder`) since the table is
    bounded in size (typically <20 groups).
    """

    def __init__(self, table_name: str) -> None:
        self._table = _DYNAMO_RESOURCE.Table(table_name)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all groups (active + inactive), sorted by order then name."""
        response = self._table.scan()
        items: list[dict[str, Any]] = response["Items"]
        # System groups (e.g. Unassigned) always sort last regardless of their numeric
        # order so they don't shift around when the user reorders real groups.
        return sorted(items, key=lambda g: (bool(g.get("system", False)), int(g.get("order", 0)), g["name"]))

    def get(self, group_id: str) -> dict[str, Any] | None:
        response = self._table.get_item(Key={"groupId": group_id})
        return response.get("Item")

    def _name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        """Case-insensitive name uniqueness check. Same race caveat as CategoryTable."""
        lower_name = name.lower()
        return any(g["name"].lower() == lower_name and g["groupId"] != exclude_id for g in self.list_all())

    def _next_order(self) -> int:
        """Next available order for a NEW non-system group.

        System groups (Unassigned) are excluded from the max computation — they
        sort last by `list_all`'s ordering, so their numeric `order` shouldn't
        push regular groups past them.
        """
        regular = [g for g in self.list_all() if not g.get("system")]
        if not regular:
            return 0
        return max(int(g.get("order", 0)) for g in regular) + 1

    def create(self, name: str, system: bool = False) -> dict[str, Any]:
        """Create a new group. `system=True` marks the row as immutable
        (no rename, no delete) — used by the "Unassigned" sentinel.
        """
        name = name.strip()
        if not name:
            raise ValueError("Group name must not be empty")
        if self._name_exists(name):
            raise ValueError(f"A group named '{name}' already exists")

        now = datetime.now(tz=UTC).isoformat()
        item: dict[str, Any] = {
            "groupId": str(ULID()),
            "name": name,
            "order": self._next_order(),
            "createdAt": now,
            "updatedAt": now,
            "system": system,
        }
        self._table.put_item(Item=item)
        _LOGGER.info("Created group: %s (%s)%s", item["name"], item["groupId"], " [system]" if system else "")
        return item

    def get_or_create_unassigned(self) -> dict[str, Any]:
        """Return the (single) `system=True` group, creating it if absent.

        The Unassigned group is a sentinel destination for orphaned categories
        (e.g. deactivated cats whose original group was deleted). It is hidden
        from rename and delete and renders without action buttons in the UI.
        """
        for g in self.list_all():
            if g.get("system"):
                return g
        return self.create("Unassigned", system=True)

    def update(self, group_id: str, name: str) -> dict[str, Any] | None:
        name = name.strip()
        if not name:
            raise ValueError("Group name must not be empty")
        if self._name_exists(name, exclude_id=group_id):
            raise ValueError(f"A group named '{name}' already exists")
        if self.get(group_id) is None:
            return None
        now = datetime.now(tz=UTC).isoformat()
        response = self._table.update_item(
            Key={"groupId": group_id},
            UpdateExpression="SET #n = :name, updatedAt = :now",
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={":name": name, ":now": now},
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]

    def delete(self, group_id: str) -> None:
        """Hard-delete a group. Caller must enforce empty-group invariant first."""
        self._table.delete_item(Key={"groupId": group_id})
        _LOGGER.info("Deleted group: %s", group_id)

    def reorder(self, group_ids_in_order: list[str]) -> None:
        """Apply a new total ordering across all groups.

        The caller passes the full ordered list; we write `order = index` on each.
        Groups not present in the list are left untouched (and will display after
        the reordered ones since their order is presumably lower / unchanged).
        """
        now = datetime.now(tz=UTC).isoformat()
        for index, gid in enumerate(group_ids_in_order):
            self._table.update_item(
                Key={"groupId": gid},
                UpdateExpression="SET #o = :o, updatedAt = :now",
                ExpressionAttributeNames={"#o": "order"},
                ExpressionAttributeValues={":o": index, ":now": now},
            )


class CategoryTable:
    """CRUD operations for budget categories."""

    def __init__(self, table_name: str) -> None:
        self._table = _DYNAMO_RESOURCE.Table(table_name)

    def list_active(self) -> list[dict[str, Any]]:
        """Return all active categories, sorted by name."""
        response = self._table.scan(
            FilterExpression="active = :val",
            ExpressionAttributeValues={":val": True},
        )
        items: list[dict[str, Any]] = response["Items"]
        return sorted(items, key=lambda c: c["name"])

    def list_all(self) -> list[dict[str, Any]]:
        """Return all categories (active and inactive), sorted by name."""
        response = self._table.scan()
        items: list[dict[str, Any]] = response["Items"]
        return sorted(items, key=lambda c: c["name"])

    def get(self, category_id: str) -> dict[str, Any] | None:
        """Return a single category by ID, or None if not found."""
        response = self._table.get_item(Key={"categoryId": category_id})
        return response.get("Item")

    def _name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        """Check if any category (active or inactive) already uses this name (case-insensitive).

        Race condition: this is a Scan-then-write pattern with no DynamoDB-level
        unique constraint on `name`. Two simultaneous category creates with the same
        name can both pass this check and both write. Accepted because (a) this is a
        single-household app, so concurrent writers are vanishingly rare; (b) adding
        a name-keyed GSI or sentinel item to enforce uniqueness would add complexity
        out of proportion to the risk. If a duplicate ever slips through, rename or
        merge manually. See docs/personal-finance-architecture.md "Category name uniqueness".
        """
        lower_name = name.lower()
        return any(cat["name"].lower() == lower_name and cat["categoryId"] != exclude_id for cat in self.list_all())

    def _next_order_in_group(self, group_id: str) -> int:
        """Next available orderInGroup, placing new categories at the end of the group."""
        cats_in_group = [c for c in self.list_all() if c.get("groupId") == group_id]
        if not cats_in_group:
            return 0
        return max(int(c.get("orderInGroup", 0)) for c in cats_in_group) + 1

    def create(self, name: str, group_id: str) -> dict[str, Any]:
        """Create a new category in `group_id`. Returns the created item."""
        name = name.strip()
        if not name:
            raise ValueError("Category name must not be empty")
        if not group_id:
            raise ValueError("group_id is required")
        if self._name_exists(name):
            raise ValueError(f"A category named '{name}' already exists")

        now = datetime.now(tz=UTC).isoformat()
        item: dict[str, Any] = {
            "categoryId": str(ULID()),
            "name": name,
            "active": True,
            "createdAt": now,
            "updatedAt": now,
            "nameHistory": [],
            "groupId": group_id,
            "orderInGroup": self._next_order_in_group(group_id),
        }

        self._table.put_item(Item=item)
        _LOGGER.info("Created category: %s (%s) in group %s", item["name"], item["categoryId"], group_id)
        return item

    def update(self, category_id: str, name: str) -> dict[str, Any] | None:
        """Update a category's name. Appends to nameHistory if the name actually changed.

        Returns the updated item, or None if not found.
        """
        name = name.strip()
        if not name:
            raise ValueError("Category name must not be empty")
        if self._name_exists(name, exclude_id=category_id):
            raise ValueError(f"A category named '{name}' already exists")

        existing = self.get(category_id)
        if existing is None:
            return None

        now = datetime.now(tz=UTC).isoformat()
        if existing["name"] == name:
            # No-op rename: only bump updatedAt, don't pollute nameHistory.
            response = self._table.update_item(
                Key={"categoryId": category_id},
                UpdateExpression="SET updatedAt = :now",
                ExpressionAttributeValues={":now": now},
                ReturnValues="ALL_NEW",
            )
            return response["Attributes"]

        # Architecture-spec history entry: previousName + replacedAt timestamp. Locked-month
        # summaries use this to render category names as they were at the time of action.
        history_entry = {"previousName": existing["name"], "replacedAt": now}
        response = self._table.update_item(
            Key={"categoryId": category_id},
            UpdateExpression=(
                "SET #n = :name, updatedAt = :now, "
                "nameHistory = list_append(if_not_exists(nameHistory, :empty), :entry)"
            ),
            ExpressionAttributeNames={"#n": "name"},
            ExpressionAttributeValues={
                ":name": name,
                ":now": now,
                ":empty": [],
                ":entry": [history_entry],
            },
            ReturnValues="ALL_NEW",
        )
        _LOGGER.info("Renamed category %s: %s -> %s", category_id, existing["name"], name)
        return response["Attributes"]

    def move_to_group(self, category_id: str, new_group_id: str) -> dict[str, Any] | None:
        """Move a category to a new group, appending it to the end of that group's order."""
        existing = self.get(category_id)
        if existing is None:
            return None
        if existing.get("groupId") == new_group_id:
            return existing
        now = datetime.now(tz=UTC).isoformat()
        response = self._table.update_item(
            Key={"categoryId": category_id},
            UpdateExpression="SET groupId = :g, orderInGroup = :o, updatedAt = :now",
            ExpressionAttributeValues={
                ":g": new_group_id,
                ":o": self._next_order_in_group(new_group_id),
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]

    def reorder_in_group(self, group_id: str, category_ids_in_order: list[str]) -> None:
        """Apply a new total ordering for categories within `group_id`.

        Each id in `category_ids_in_order` is updated with its `orderInGroup`
        set to its index, and its `groupId` set to `group_id` (so this also
        functions as a bulk move when called with categories from other groups).
        """
        now = datetime.now(tz=UTC).isoformat()
        for index, cid in enumerate(category_ids_in_order):
            self._table.update_item(
                Key={"categoryId": cid},
                UpdateExpression="SET groupId = :g, orderInGroup = :o, updatedAt = :now",
                ExpressionAttributeValues={":g": group_id, ":o": index, ":now": now},
            )

    def deactivate(self, category_id: str) -> dict[str, Any] | None:
        """Soft-delete a category by setting active=False. Returns the updated item, or None if not found."""
        if self.get(category_id) is None:
            return None

        now = datetime.now(tz=UTC).isoformat()
        response = self._table.update_item(
            Key={"categoryId": category_id},
            UpdateExpression="SET active = :val, updatedAt = :now",
            ExpressionAttributeValues={":val": False, ":now": now},
            ReturnValues="ALL_NEW",
        )
        _LOGGER.info("Deactivated category %s", category_id)
        return response["Attributes"]

    def delete(self, category_id: str) -> None:
        """Hard-delete the Category row. No soft-delete fallback — used by admin hard-delete only."""
        self._table.delete_item(Key={"categoryId": category_id})

    def reactivate(self, category_id: str) -> dict[str, Any] | None:
        """Re-activate a deactivated category. Returns the updated item, or None if not found."""
        if self.get(category_id) is None:
            return None

        now = datetime.now(tz=UTC).isoformat()
        response = self._table.update_item(
            Key={"categoryId": category_id},
            UpdateExpression="SET active = :val, updatedAt = :now",
            ExpressionAttributeValues={":val": True, ":now": now},
            ReturnValues="ALL_NEW",
        )
        _LOGGER.info("Reactivated category %s", category_id)
        return response["Attributes"]


class BudgetTable:
    """Monthly budget target management."""

    def __init__(self, table_name: str) -> None:
        self._table = _DYNAMO_RESOURCE.Table(table_name)

    def get_targets(self, year_month: str) -> list[dict[str, Any]]:
        """Get all budget targets for a given month (YYYY-MM)."""
        response = self._table.query(
            KeyConditionExpression="yearMonth = :ym",
            ExpressionAttributeValues={":ym": year_month},
        )
        return response["Items"]

    def put_targets(self, year_month: str, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Set budget targets for a month. Overwrites all targets for the given month."""
        existing = self.get_targets(year_month)
        with self._table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"yearMonth": year_month, "categoryId": item["categoryId"]})

        items: list[dict[str, Any]] = []
        with self._table.batch_writer() as batch:
            for target in targets:
                item: dict[str, Any] = {
                    "yearMonth": year_month,
                    "categoryId": target["categoryId"],
                    "amount": target["amount"],
                }
                batch.put_item(Item=item)
                items.append(item)

        _LOGGER.info("Set %d targets for %s", len(items), year_month)
        return items

    def scan_all(self) -> list[dict[str, Any]]:
        """Return every row in the table.

        Used by densification to load the full state into memory before walking
        forward through missed months. The table is bounded in size (categories
        x months tracked) so a Scan is cheaper than the equivalent fan-out of
        per-month Queries.
        """
        items: list[dict[str, Any]] = []
        params: dict[str, Any] = {}
        while True:
            response = self._table.scan(**params)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return items

    def put_single(self, year_month: str, category_id: str, amount: Any) -> None:
        """Write a single budget row. Used by densification to fill missing cells."""
        self._table.put_item(
            Item={"yearMonth": year_month, "categoryId": category_id, "amount": amount},
        )

    def delete_single(self, year_month: str, category_id: str) -> None:
        """Delete a single budget row. Used by /pin when clearing a pin (amount=null)."""
        self._table.delete_item(Key={"yearMonth": year_month, "categoryId": category_id})

    def find_future_months_with_category(self, category_id: str, after_month: str) -> list[str]:
        """Return sorted list of yearMonth values > after_month that contain the given categoryId."""
        months: set[str] = set()
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid AND yearMonth > :ym",
            "ExpressionAttributeValues": {":cid": category_id, ":ym": after_month},
            "ProjectionExpression": "yearMonth",
        }
        while True:
            response = self._table.scan(**params)
            for item in response["Items"]:
                months.add(str(item["yearMonth"]))
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted(months)

    def count_rows_for_category(self, category_id: str) -> int:
        """Count every Budget row referencing the given categoryId. Used by hard-delete preview."""
        count = 0
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid",
            "ExpressionAttributeValues": {":cid": category_id},
            "Select": "COUNT",
        }
        while True:
            response = self._table.scan(**params)
            count += response.get("Count", 0)
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return count

    def find_past_months_with_category(self, category_id: str, before_month: str) -> list[str]:
        """Return sorted list of yearMonth values < before_month that contain the given categoryId.

        Used by the hard-delete preview to highlight historical data the delete would erase.
        The caller filters by editability state if it needs only locked vs grace.
        """
        months: set[str] = set()
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid AND yearMonth < :ym",
            "ExpressionAttributeValues": {":cid": category_id, ":ym": before_month},
            "ProjectionExpression": "yearMonth",
        }
        while True:
            response = self._table.scan(**params)
            for item in response["Items"]:
                months.add(str(item["yearMonth"]))
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted(months)

    def delete_all_for_category(self, category_id: str) -> int:
        """Cascade-delete every Budget row referencing the given categoryId. Returns count.

        Used by hard-delete only — soft-delete (/deactivate) drops just the future pin
        rows. See docs/personal-finance-architecture.md "Hard delete semantics".
        """
        keys: list[dict[str, str]] = []
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid",
            "ExpressionAttributeValues": {":cid": category_id},
            "ProjectionExpression": "yearMonth, categoryId",
        }
        while True:
            response = self._table.scan(**params)
            keys.extend(
                {"yearMonth": str(item["yearMonth"]), "categoryId": str(item["categoryId"])}
                for item in response["Items"]
            )
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        if not keys:
            return 0
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)
        _LOGGER.info("Hard-deleted %d Budget rows for category %s", len(keys), category_id)
        return len(keys)


class TransactionsTable:
    """Transaction storage and querying."""

    def __init__(self, table_name: str) -> None:
        self._table = _DYNAMO_RESOURCE.Table(table_name)

    def list_for_month(self, year_month: str) -> list[dict[str, Any]]:
        """List all transactions for a given month (YYYY-MM), sorted by sortId."""
        response = self._table.query(
            KeyConditionExpression="yearMonth = :ym",
            ExpressionAttributeValues={":ym": year_month},
        )
        return response["Items"]

    def create(
        self,
        year_month: str,
        transaction_date: str,
        description: str,
        amount: int,
        category_id: str,
    ) -> dict[str, Any]:
        """Create a single transaction. Returns the created item."""
        description = description.strip()
        if not description:
            raise ValueError("Transaction description must not be empty")

        now = datetime.now(tz=UTC).isoformat()
        sort_id = f"{transaction_date}#{ULID()}"

        item: dict[str, Any] = {
            "yearMonth": year_month,
            "sortId": sort_id,
            "transactionDate": transaction_date,
            "description": description,
            "amount": amount,
            "categoryId": category_id,
            "createdAt": now,
        }

        self._table.put_item(Item=item)
        _LOGGER.info("Created transaction %s in %s", sort_id, year_month)
        return item

    def batch_create(self, transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create multiple transactions in a batch. Each dict must have yearMonth,
        transactionDate, description, amount, categoryId. Returns created items."""
        now = datetime.now(tz=UTC).isoformat()
        items: list[dict[str, Any]] = []

        with self._table.batch_writer() as batch:
            for txn in transactions:
                sort_id = f"{txn['transactionDate']}#{ULID()}"
                item: dict[str, Any] = {
                    "yearMonth": txn["yearMonth"],
                    "sortId": sort_id,
                    "transactionDate": txn["transactionDate"],
                    "description": txn["description"].strip(),
                    "amount": txn["amount"],
                    "categoryId": txn["categoryId"],
                    "createdAt": now,
                }
                batch.put_item(Item=item)
                items.append(item)

        _LOGGER.info("Batch created %d transactions", len(items))
        return items

    def update(self, year_month: str, sort_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update a transaction's mutable fields (description, amount, categoryId).
        Returns the updated item, or None if not found."""
        response = self._table.get_item(Key={"yearMonth": year_month, "sortId": sort_id})
        if "Item" not in response:
            return None

        update_parts: list[str] = []
        attr_values: dict[str, Any] = {}
        attr_names: dict[str, str] = {}

        for field in ("description", "amount", "categoryId"):
            if field in updates:
                placeholder = f":{field}"
                update_parts.append(f"#{field} = {placeholder}")
                attr_values[placeholder] = updates[field]
                attr_names[f"#{field}"] = field

        if not update_parts:
            return response["Item"]

        result = self._table.update_item(
            Key={"yearMonth": year_month, "sortId": sort_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
            ReturnValues="ALL_NEW",
        )
        _LOGGER.info("Updated transaction %s/%s", year_month, sort_id)
        return result["Attributes"]

    def delete(self, year_month: str, sort_id: str) -> bool:
        """Delete a transaction. Returns True if deleted, False if not found."""
        response = self._table.get_item(Key={"yearMonth": year_month, "sortId": sort_id})
        if "Item" not in response:
            return False

        self._table.delete_item(Key={"yearMonth": year_month, "sortId": sort_id})
        _LOGGER.info("Deleted transaction %s/%s", year_month, sort_id)
        return True

    def batch_delete(self, items: list[dict[str, str]]) -> int:
        """Delete multiple transactions. Returns the number of items deleted.

        Each item must have 'yearMonth' and 'sortId' keys. Uses DynamoDB
        batch_writer which handles chunking into 25-item batches automatically.
        """
        count = 0
        with self._table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"yearMonth": item["yearMonth"], "sortId": item["sortId"]})
                count += 1
        _LOGGER.info("Batch deleted %d transactions", count)
        return count

    def count_rows_for_category(self, category_id: str) -> int:
        """Count every Transactions row referencing the given categoryId. Used by hard-delete preview."""
        count = 0
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid",
            "ExpressionAttributeValues": {":cid": category_id},
            "Select": "COUNT",
        }
        while True:
            response = self._table.scan(**params)
            count += response.get("Count", 0)
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return count

    def delete_all_for_category(self, category_id: str) -> int:
        """Cascade-delete every Transactions row referencing the given categoryId. Returns count.

        Hard-delete only — there's no soft-delete equivalent for transactions.
        See docs/personal-finance-architecture.md "Hard delete semantics".
        """
        keys: list[dict[str, str]] = []
        params: dict[str, Any] = {
            "FilterExpression": "categoryId = :cid",
            "ExpressionAttributeValues": {":cid": category_id},
            "ProjectionExpression": "yearMonth, sortId",
        }
        while True:
            response = self._table.scan(**params)
            keys.extend(
                {"yearMonth": str(item["yearMonth"]), "sortId": str(item["sortId"])} for item in response["Items"]
            )
            if "LastEvaluatedKey" not in response:
                break
            params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        if not keys:
            return 0
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)
        _LOGGER.info("Hard-deleted %d Transactions for category %s", len(keys), category_id)
        return len(keys)


_AUDIT_PARTITION = "AUDIT"


class AuditLogTable:
    """Budget audit log writes and reads.

    Single-partition design: PK is always the literal string "AUDIT", SK is a ULID
    that sorts chronologically. Recent-N reads are one Query with
    ScanIndexForward=false; no month-walking required.
    """

    def __init__(self, table_name: str) -> None:
        self._table = _DYNAMO_RESOURCE.Table(table_name)

    def write_entry(
        self,
        effective_year_month: str | None,
        category_id: str,
        action: str,
        explanation: str,
        user: dict[str, str],
        changes: dict[str, Any],
        override: bool = False,
    ) -> dict[str, Any]:
        """Write a single audit log entry. Returns the created item.

        `user` is the JWT-claims snapshot {sub, email, username} captured at request time
        per the architecture doc's "Audit user identity" section.
        `effective_year_month` may be None for actions not scoped to a single month
        (e.g. CATEGORY_HARD_DELETE).
        """
        now = datetime.now(tz=UTC)

        item: dict[str, Any] = {
            "entityType": _AUDIT_PARTITION,
            "sortId": str(ULID()),
            "changedAt": now.isoformat(),
            "effectiveYearMonth": effective_year_month,
            "categoryId": category_id,
            "action": action,
            "explanation": explanation,
            "user": user,
            "override": override,
            "changes": changes,
        }

        self._table.put_item(Item=item)
        _LOGGER.info(
            "Audit: %s on %s/%s by %s%s",
            action,
            effective_year_month,
            category_id,
            user.get("email", user.get("sub", "?")),
            " (override)" if override else "",
        )
        return item

    def read_recent_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the last N audit log entries, newest first.

        Single Query against the AUDIT partition with ScanIndexForward=False so
        DynamoDB walks the sort key in descending ULID order.
        """
        response = self._table.query(
            KeyConditionExpression="entityType = :pk",
            ExpressionAttributeValues={":pk": _AUDIT_PARTITION},
            ScanIndexForward=False,
            Limit=limit,
        )
        return list(response["Items"])


def compute_summary(
    budget: BudgetTable,
    transactions: TransactionsTable,
    category_table: CategoryTable,
    year_month: str,
    now: datetime,
) -> dict[str, Any]:
    """Compute budget vs actuals for a given month per Spec 5.

    Membership rules (architecture: "Summary view membership rules"):
    - **Editable months** — currently active categories, plus any category
      (active or inactive) with at least one transaction with amount != 0 in this month.
    - **Locked months** — every category referenced by a budget row (any amount,
      including $0) OR at least one transaction, regardless of current `active` flag.

    Each row carries `name` (current) and `historicalName` (set only for locked
    months when the category was renamed AFTER this year-month — see
    "Display names on locked months"). The frontend renders the pair as
    `historicalName (renamed to: name)`.

    Amounts are signed (positive=expense, negative=income/return). Aggregation is
    a straight sum — no `abs()`, no sign flips. A refund or income row reduces the
    category's actual, which makes delta (= budgeted - actual) larger.
    """
    txns = transactions.list_for_month(year_month)
    categories_all = category_table.list_all()
    category_by_id = {c["categoryId"]: c for c in categories_all}

    current_ym = f"{now.year:04d}-{now.month:02d}"
    is_future = year_month > current_ym

    # Densification can write `amount=null` when walk-back finds no prior history
    # (architecture: "New category, no prior history"). Null means "no target" —
    # for aggregation we treat it as 0 since there's nothing to subtract from.
    #
    # For dense months (year_month <= current_ym) every active category has a
    # stored row; a direct query is sufficient. For future months the table is
    # sparse — only explicit pins live there — so the effective budgeted value
    # is whatever walk-back resolves to, per architecture's "Display of a future
    # month is resolved per category" rule.
    budget_by_category: dict[str, Decimal] = {}
    if is_future:
        rows = budget.scan_all()
        by_key: dict[tuple[str, str], Any] = {(r["yearMonth"], r["categoryId"]): r["amount"] for r in rows}
        for cat in categories_all:
            cat_id = cat["categoryId"]
            raw = _walk_back_amount(by_key, year_month, cat_id)
            if raw is not None:
                budget_by_category[cat_id] = Decimal("0") if raw is None else Decimal(str(raw))
    else:
        for target in budget.get_targets(year_month):
            raw = target.get("amount")
            budget_by_category[target["categoryId"]] = Decimal("0") if raw is None else Decimal(str(raw))

    actual_by_category: dict[str, Decimal] = {}
    nonzero_txn_cat_ids: set[str] = set()
    for txn in txns:
        cat_id = txn["categoryId"]
        raw_amount = txn.get("amount")
        amount = Decimal("0") if raw_amount is None else Decimal(str(raw_amount))
        actual_by_category[cat_id] = actual_by_category.get(cat_id, Decimal("0")) + amount
        if amount != 0:
            nonzero_txn_cat_ids.add(cat_id)

    state = editability(year_month, now)
    is_locked = state == "LOCKED"

    if is_locked:
        # Locked rule: every category with ANY budget row or ANY transaction (zero or not).
        # Budget rows are never removed on deactivation, so they're the historical signal.
        member_ids = set(budget_by_category.keys()) | {t["categoryId"] for t in txns}
    else:
        # Editable rule: active categories + (inactive with non-zero txn).
        active_ids = {c["categoryId"] for c in categories_all if c.get("active", False)}
        member_ids = active_ids | nonzero_txn_cat_ids
    all_category_ids = sorted(member_ids)

    month_end_utc = _month_end_utc(year_month) if is_locked else None

    categories: list[dict[str, Any]] = []
    total_budgeted = Decimal("0")
    total_actual = Decimal("0")

    for cat_id in all_category_ids:
        budgeted = budget_by_category.get(cat_id, Decimal("0"))
        actual = actual_by_category.get(cat_id, Decimal("0"))
        delta = budgeted - actual

        cat = category_by_id.get(cat_id)
        name = str(cat["name"]) if cat else cat_id
        historical_name: str | None = None
        if is_locked and cat is not None and month_end_utc is not None:
            historical_name = _resolve_historical_name(cat, month_end_utc)

        categories.append(
            {
                "categoryId": cat_id,
                "name": name,
                "historicalName": historical_name,
                "budgeted": int(budgeted),
                "actual": int(actual),
                "delta": int(delta),
            }
        )

        total_budgeted += budgeted
        total_actual += actual

    return {
        "yearMonth": year_month,
        "state": state,
        "categories": categories,
        "totals": {
            "budgeted": int(total_budgeted),
            "actual": int(total_actual),
            "delta": int(total_budgeted - total_actual),
        },
    }
