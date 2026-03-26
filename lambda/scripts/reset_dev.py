"""Wipe all items from the dev-stage Budget DynamoDB tables."""

import sys
from typing import Any

import boto3

_DEV_TABLES: dict[str, list[str]] = {
    "Category-dev": ["categoryId"],
    "Budget-dev": ["yearMonth", "categoryId"],
    "BudgetAuditLog-dev": ["entityType", "sortId"],
    "Transactions-dev": ["yearMonth", "sortId"],
}


def _delete_all_items(table_name: str, key_attrs: list[str]) -> int:
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    deleted = 0
    # Value type is Any because ExclusiveStartKey is a dict, not a string —
    # an over-narrow `dict[str, str]` annotation would reject the assignment below.
    scan_kwargs: dict[str, Any] = {}
    while True:
        response = table.scan(**scan_kwargs)
        items = response.get("Items", [])
        if not items:
            break

        with table.batch_writer() as batch:
            for item in items:
                key = {attr: item[attr] for attr in key_attrs}
                batch.delete_item(Key=key)
                deleted += 1

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    return deleted


def main() -> None:
    print("Resetting dev DynamoDB tables...")
    print()

    total = 0
    for table_name, key_attrs in _DEV_TABLES.items():
        count = _delete_all_items(table_name, key_attrs)
        print(f"  {table_name}: deleted {count} items")
        total += count

    print()
    print(f"Done. Deleted {total} total items.")


if __name__ == "__main__":
    if "--confirm" not in sys.argv:
        print("This will delete ALL items from the dev Budget tables.")
        print("Run with --confirm to proceed.")
        sys.exit(1)
    main()
