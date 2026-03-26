"""Tests for the budget admin claim parser."""

from typing import Any

from corderohq.budget.auth import is_budget_admin


def _event_with_groups(groups: Any) -> dict[str, Any]:
    return {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"cognito:groups": groups}}},
        },
    }


class TestEmptyOrMissing:
    def test_empty_event_returns_false(self) -> None:
        assert is_budget_admin({}, "dev") is False

    def test_event_without_request_context_returns_false(self) -> None:
        assert is_budget_admin({"body": "{}"}, "dev") is False

    def test_event_without_claims_returns_false(self) -> None:
        event = {"requestContext": {"authorizer": {"jwt": {}}}}
        assert is_budget_admin(event, "dev") is False

    def test_no_groups_claim_returns_false(self) -> None:
        event = _event_with_groups(None)
        event["requestContext"]["authorizer"]["jwt"]["claims"].pop("cognito:groups")
        assert is_budget_admin(event, "dev") is False

    def test_empty_string_groups_returns_false(self) -> None:
        assert is_budget_admin(_event_with_groups(""), "dev") is False

    def test_whitespace_only_groups_returns_false(self) -> None:
        assert is_budget_admin(_event_with_groups("   "), "dev") is False


class TestListShape:
    def test_list_with_matching_group_returns_true(self) -> None:
        event = _event_with_groups(["budget-admin-dev"])
        assert is_budget_admin(event, "dev") is True

    def test_list_with_non_matching_group_returns_false(self) -> None:
        event = _event_with_groups(["other-group"])
        assert is_budget_admin(event, "dev") is False

    def test_list_with_wrong_stage_admin_returns_false(self) -> None:
        event = _event_with_groups(["budget-admin-prod"])
        assert is_budget_admin(event, "dev") is False

    def test_list_with_multiple_groups_including_match_returns_true(self) -> None:
        event = _event_with_groups(["other", "budget-admin-dev", "third"])
        assert is_budget_admin(event, "dev") is True

    def test_empty_list_returns_false(self) -> None:
        assert is_budget_admin(_event_with_groups([]), "dev") is False


class TestJsonStringShape:
    def test_json_list_string_with_match_returns_true(self) -> None:
        event = _event_with_groups('["budget-admin-dev", "other"]')
        assert is_budget_admin(event, "dev") is True

    def test_json_list_string_without_match_returns_false(self) -> None:
        event = _event_with_groups('["other-group"]')
        assert is_budget_admin(event, "dev") is False

    def test_malformed_json_returns_false(self) -> None:
        event = _event_with_groups('["unclosed')
        assert is_budget_admin(event, "dev") is False

    def test_json_non_list_returns_false(self) -> None:
        event = _event_with_groups('{"key": "value"}')
        assert is_budget_admin(event, "dev") is False


class TestCommaSeparatedShape:
    def test_comma_separated_with_match_returns_true(self) -> None:
        event = _event_with_groups("budget-admin-dev,other-group")
        assert is_budget_admin(event, "dev") is True

    def test_comma_separated_with_match_and_spaces_returns_true(self) -> None:
        event = _event_with_groups("other, budget-admin-dev , third")
        assert is_budget_admin(event, "dev") is True

    def test_comma_separated_without_match_returns_false(self) -> None:
        event = _event_with_groups("group-a,group-b")
        assert is_budget_admin(event, "dev") is False

    def test_single_group_string_with_match_returns_true(self) -> None:
        event = _event_with_groups("budget-admin-dev")
        assert is_budget_admin(event, "dev") is True

    def test_single_group_string_without_match_returns_false(self) -> None:
        event = _event_with_groups("other-group")
        assert is_budget_admin(event, "dev") is False


class TestStageIsolation:
    def test_dev_admin_is_not_prod_admin(self) -> None:
        event = _event_with_groups(["budget-admin-dev"])
        assert is_budget_admin(event, "prod") is False

    def test_prod_admin_is_not_dev_admin(self) -> None:
        event = _event_with_groups(["budget-admin-prod"])
        assert is_budget_admin(event, "dev") is False
