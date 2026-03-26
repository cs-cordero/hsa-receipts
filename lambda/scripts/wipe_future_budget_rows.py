"""One-shot wipe of eagerly-materialized future-month Budget rows.

Before CP5, `GET /api/budget/{ym}` would lazily carry forward and write rows
into future months on read. After CP5, future months are sparse — only
explicit pins live there, and unpinned values are resolved via walk-back at
display time. Any rows left over from the old behavior would now masquerade
as pins and surprise the user.

Run once per stage after the CP5 deploy. Idempotent: re-running on a clean
table is a no-op.

Usage:
    uv run python lambda/scripts/wipe_future_budget_rows.py --stage dev
    uv run python lambda/scripts/wipe_future_budget_rows.py --stage prod
"""

import argparse
from datetime import UTC, datetime
from typing import Any

import boto3


def _current_year_month() -> str:
    now = datetime.now(tz=UTC)
    return f"{now.year:04d}-{now.month:02d}"


def wipe_future_rows(stage: str, dry_run: bool) -> int:
    table_name = f"Budget-{stage}"
    table = boto3.resource("dynamodb").Table(table_name)
    current_ym = _current_year_month()

    to_delete: list[dict[str, Any]] = []
    params: dict[str, Any] = {
        "FilterExpression": "yearMonth > :ym",
        "ExpressionAttributeValues": {":ym": current_ym},
        "ProjectionExpression": "yearMonth, categoryId",
    }
    while True:
        response = table.scan(**params)
        to_delete.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    print(f"[{stage}] current_ym={current_ym}, found {len(to_delete)} future rows")
    if not to_delete:
        return 0

    if dry_run:
        for row in to_delete[:20]:
            print(f"  would delete: {row['yearMonth']} / {row['categoryId']}")
        if len(to_delete) > 20:
            print(f"  ... and {len(to_delete) - 20} more")
        return len(to_delete)

    with table.batch_writer() as batch:
        for row in to_delete:
            batch.delete_item(Key={"yearMonth": row["yearMonth"], "categoryId": row["categoryId"]})

    print(f"[{stage}] deleted {len(to_delete)} rows")
    return len(to_delete)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("dev", "prod"))
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted without writing")
    args = parser.parse_args()
    wipe_future_rows(args.stage, args.dry_run)


if __name__ == "__main__":
    main()
