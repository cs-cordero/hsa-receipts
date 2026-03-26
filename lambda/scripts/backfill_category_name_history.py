"""One-shot backfill of `nameHistory: []` on existing Category rows.

CP8 added a nameHistory list to the Category schema (architecture: "Category
lifecycle"). Existing rows pre-date the field, so this script scans each stage's
Category table and sets `nameHistory = []` on any row missing the attribute.

Idempotent: re-runs after the field is present are no-ops.

Usage:
    uv run python lambda/scripts/backfill_category_name_history.py --stage dev
    uv run python lambda/scripts/backfill_category_name_history.py --stage prod
"""

import argparse

import boto3


def backfill(stage: str, dry_run: bool) -> int:
    table_name = f"Category-{stage}"
    table = boto3.resource("dynamodb").Table(table_name)

    response = table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    needs_backfill = [item for item in items if "nameHistory" not in item]
    print(f"[{stage}] scanned {len(items)} rows, {len(needs_backfill)} missing nameHistory")
    if not needs_backfill:
        return 0

    if dry_run:
        for item in needs_backfill[:20]:
            print(f"  would set nameHistory=[] on {item['categoryId']} ({item['name']})")
        if len(needs_backfill) > 20:
            print(f"  ... and {len(needs_backfill) - 20} more")
        return len(needs_backfill)

    for item in needs_backfill:
        # if_not_exists guards against a race with a concurrent rename that sets
        # nameHistory itself between our scan and update.
        table.update_item(
            Key={"categoryId": item["categoryId"]},
            UpdateExpression="SET nameHistory = if_not_exists(nameHistory, :empty)",
            ExpressionAttributeValues={":empty": []},
        )

    print(f"[{stage}] backfilled {len(needs_backfill)} rows")
    return len(needs_backfill)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("dev", "prod"))
    parser.add_argument("--dry-run", action="store_true", help="Print what would be updated without writing")
    args = parser.parse_args()
    backfill(args.stage, args.dry_run)


if __name__ == "__main__":
    main()
