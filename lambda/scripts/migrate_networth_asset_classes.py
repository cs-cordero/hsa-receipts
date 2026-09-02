"""One-shot migration: single asset class → per-class model (per-value redesign).

Converts pre-per-value net-worth data to the Chunk 2 shapes:

1. `Account-{stage}`: `assetClass` (single string) → `assetClasses` (list). The
   deprecated `us_equity` is remapped to `us_equity_large_cap` (we can't know the
   historical large/small split; the user re-splits going forward). The old
   `assetClass` attribute is removed.
2. `NetWorthSnapshot-{stage}`: scalar `value` → `byAssetClass` map keyed by the
   account's (remapped) class. The old `value` attribute is removed.

Idempotent: rows already carrying `assetClasses` / `byAssetClass` are skipped, so it
is safe to re-run (dev first, then prod).

Usage:
    uv run python lambda/scripts/migrate_networth_asset_classes.py --stage dev
    uv run python lambda/scripts/migrate_networth_asset_classes.py --stage dev --apply
    uv run python lambda/scripts/migrate_networth_asset_classes.py --stage prod --apply
"""

import argparse
from typing import Any

import boto3

# Legacy → current asset-class remap (self-contained so this one-shot keeps working
# after the shared helper is removed in the Chunk 4 cleanup). `us_equity` can't be
# split by ratio, so it defaults to large cap; the user re-splits going forward.
_LEGACY_ASSET_CLASS_REMAP = {"us_equity": "us_equity_large_cap"}


def remap_legacy_asset_class(value: str) -> str:
    return _LEGACY_ASSET_CLASS_REMAP.get(value, value)


def _scan_all(table: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    response = table.scan()
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    return items


def migrate(stage: str, apply: bool) -> None:
    dynamodb = boto3.resource("dynamodb")
    account_table = dynamodb.Table(f"Account-{stage}")
    snapshot_table = dynamodb.Table(f"NetWorthSnapshot-{stage}")

    accounts = _scan_all(account_table)
    snapshots = _scan_all(snapshot_table)

    # --- Accounts: assetClass → assetClasses ---
    account_class: dict[str, str] = {}  # accountId → current (remapped) primary class
    account_writes = 0
    for acct in accounts:
        account_id = acct["accountId"]
        if "assetClasses" in acct:
            # Already migrated; capture its primary class for snapshot keying.
            classes = acct["assetClasses"]
            if classes:
                account_class[account_id] = classes[0]
            continue
        legacy = acct.get("assetClass")
        if legacy is None:
            print(f"  ! account {account_id} ({acct.get('name')}) has no assetClass; skipping")
            continue
        remapped = remap_legacy_asset_class(legacy)
        account_class[account_id] = remapped
        account_writes += 1
        print(f"  account {account_id} ({acct.get('name')}): assetClass={legacy} → assetClasses=[{remapped}]")
        if apply:
            account_table.update_item(
                Key={"accountId": account_id},
                UpdateExpression="SET assetClasses = :ac REMOVE assetClass",
                ExpressionAttributeValues={":ac": [remapped]},
            )

    # --- Snapshots: value → byAssetClass ---
    snapshot_writes = 0
    for snap in snapshots:
        if "byAssetClass" in snap:
            continue  # already migrated
        account_id = snap["accountId"]
        year_month = snap["yearMonth"]
        value = snap.get("value")
        if value is None:
            print(f"  ! snapshot {year_month}/{account_id} has no value; skipping")
            continue
        cls = account_class.get(account_id)
        if cls is None:
            print(f"  ! snapshot {year_month}/{account_id} references unknown account; skipping")
            continue
        snapshot_writes += 1
        print(f"  snapshot {year_month}/{account_id}: value={value} → byAssetClass={{{cls}: {value}}}")
        if apply:
            snapshot_table.update_item(
                Key={"yearMonth": year_month, "accountId": account_id},
                UpdateExpression="SET byAssetClass = :m REMOVE #v",
                ExpressionAttributeNames={"#v": "value"},
                ExpressionAttributeValues={":m": {cls: value}},
            )

    mode = "APPLIED" if apply else "DRY RUN (pass --apply to write)"
    print(
        f"\n[{stage}] {mode}: {account_writes} account(s) and {snapshot_writes} snapshot row(s) "
        f"needed migration (of {len(accounts)} accounts, {len(snapshots)} snapshots)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=["dev", "prod"])
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    args = parser.parse_args()
    migrate(args.stage, args.apply)


if __name__ == "__main__":
    main()
