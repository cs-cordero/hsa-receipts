"""JWT claim parsing for the budget app's admin override.

Admins are members of a stage-specific Cognito group named `budget-admin-{stage}`.
"""

from __future__ import annotations

import json
from typing import Any


def is_budget_admin(event: dict[str, Any], stage: str) -> bool:
    """Return True if the request's JWT carries the `budget-admin-{stage}` group claim.

    The `cognito:groups` claim arrives from API Gateway as either:
    - A JSON-encoded list string (e.g., `'["budget-admin-dev", "other-group"]'`)
    - A comma-separated string (e.g., `"budget-admin-dev,other-group"`)
    - An actual list (when the test harness passes claims directly)

    All three shapes are handled.
    """
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    groups_raw = claims.get("cognito:groups", "")
    expected = f"budget-admin-{stage}"

    if isinstance(groups_raw, list):
        return expected in groups_raw

    if isinstance(groups_raw, str):
        stripped = groups_raw.strip()
        if not stripped:
            return False
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return False
            return isinstance(parsed, list) and expected in parsed
        return expected in [g.strip() for g in stripped.split(",")]

    return False
