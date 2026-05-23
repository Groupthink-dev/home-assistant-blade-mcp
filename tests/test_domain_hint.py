"""Unit tests for DD-338 A.2.dom.c per-record domain_hint computation."""

from __future__ import annotations

from typing import Any

import pytest

from ha_blade_mcp.domain_hint import (
    Pattern,
    compute_domain_hint,
    load_patterns_from_yaml,
)


def _ha_projector(record: dict[str, Any], field: str) -> Any:
    """Minimal HA-shaped projector mirroring server._field_projector.

    Kept in the test module so the test exercises the contract shape
    without importing server.py (which would force a FastMCP boot).
    """
    if field == "entity_id":
        return record.get("entity_id")
    if field == "entity_namespace":
        eid = record.get("entity_id")
        if isinstance(eid, str) and "." in eid:
            return eid.split(".", 1)[0]
        return None
    if field == "friendly_name":
        attrs = record.get("attributes")
        if isinstance(attrs, dict):
            return attrs.get("friendly_name")
        return None
    if field == "area_id":
        attrs = record.get("attributes")
        if isinstance(attrs, dict):
            return attrs.get("area_id")
        return None
    if field == "state":
        return record.get("state")
    if field == "labels":
        return record.get("labels")
    return None


# ---------------------------------------------------------------------------
# compute_domain_hint
# ---------------------------------------------------------------------------


class TestComputeDomainHint:
    def test_empty_patterns_returns_none(self) -> None:
        record = {"entity_id": "light.kitchen"}
        assert compute_domain_hint(record, [], _ha_projector) is None

    def test_equals_match_on_entity_namespace(self) -> None:
        patterns = [Pattern(field="entity_namespace", op="equals", value="light", domain="home")]
        record = {"entity_id": "light.kitchen"}
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"

    def test_contains_match_on_friendly_name(self) -> None:
        patterns = [Pattern(field="friendly_name", op="contains", value="Kitchen", domain="home")]
        record = {
            "entity_id": "sensor.zwave_node_temp_1",
            "attributes": {"friendly_name": "Kitchen Temperature"},
        }
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"

    def test_glob_match_on_entity_id(self) -> None:
        patterns = [Pattern(field="entity_id", op="glob", value="alarm_control_panel.*", domain="home")]
        record = {"entity_id": "alarm_control_panel.front_door"}
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"

    def test_first_match_wins(self) -> None:
        patterns = [
            Pattern(field="entity_namespace", op="equals", value="light", domain="home"),
            Pattern(field="entity_namespace", op="equals", value="light", domain="personal"),
        ]
        record = {"entity_id": "light.kitchen"}
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"

    def test_projector_returns_none_no_match(self) -> None:
        patterns = [Pattern(field="friendly_name", op="contains", value="Kitchen", domain="home")]
        # No attributes dict ⇒ projector returns None
        record = {"entity_id": "light.kitchen"}
        assert compute_domain_hint(record, patterns, _ha_projector) is None

    def test_list_valued_projected_field_iterates(self) -> None:
        patterns = [Pattern(field="labels", op="equals", value="critical", domain="home")]
        record = {"entity_id": "binary_sensor.smoke", "labels": ["normal", "critical"]}
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"

    def test_unknown_op_never_matches(self) -> None:
        patterns = [Pattern(field="entity_namespace", op="regex", value="light.*", domain="home")]
        record = {"entity_id": "light.kitchen"}
        assert compute_domain_hint(record, patterns, _ha_projector) is None

    def test_area_id_attribute_projection(self) -> None:
        patterns = [Pattern(field="area_id", op="equals", value="kitchen", domain="home")]
        record = {"entity_id": "light.bench", "attributes": {"area_id": "kitchen"}}
        assert compute_domain_hint(record, patterns, _ha_projector) == "home"


# ---------------------------------------------------------------------------
# load_patterns_from_yaml
# ---------------------------------------------------------------------------


class TestLoadPatternsFromYaml:
    def test_empty_string_returns_empty(self) -> None:
        assert load_patterns_from_yaml("") == []

    def test_well_formed_yaml(self) -> None:
        yaml_str = """
patterns:
  - field: friendly_name
    op: contains
    value: Kitchen
    domain: home
  - field: entity_namespace
    op: equals
    value: light
    domain: home
"""
        patterns = load_patterns_from_yaml(yaml_str)
        assert len(patterns) == 2
        assert patterns[0] == Pattern("friendly_name", "contains", "Kitchen", "home")
        assert patterns[1] == Pattern("entity_namespace", "equals", "light", "home")

    def test_missing_patterns_key_returns_empty(self) -> None:
        assert load_patterns_from_yaml("other_key: 42") == []

    def test_malformed_yaml_returns_empty(self) -> None:
        assert load_patterns_from_yaml("patterns: [unbalanced") == []

    def test_non_list_patterns_returns_empty(self) -> None:
        assert load_patterns_from_yaml("patterns: 42") == []

    def test_partial_entries_skipped(self) -> None:
        # Second entry missing `domain` ⇒ skipped, first entry preserved
        yaml_str = """
patterns:
  - field: entity_namespace
    op: equals
    value: light
    domain: home
  - field: entity_namespace
    op: equals
    value: sensor
"""
        patterns = load_patterns_from_yaml(yaml_str)
        assert len(patterns) == 1
        assert patterns[0].domain == "home"

    def test_non_dict_entries_skipped(self) -> None:
        yaml_str = """
patterns:
  - "not a dict"
  - field: entity_namespace
    op: equals
    value: light
    domain: home
"""
        patterns = load_patterns_from_yaml(yaml_str)
        assert len(patterns) == 1


# ---------------------------------------------------------------------------
# Defensive guards
# ---------------------------------------------------------------------------


class TestDefensiveGuards:
    def test_none_projected_value_never_matches(self) -> None:
        patterns = [Pattern(field="entity_id", op="equals", value="anything", domain="home")]
        # Projector returns None for unknown field
        record: dict[str, Any] = {}
        assert compute_domain_hint(record, patterns, _ha_projector) is None

    @pytest.mark.parametrize("op", ["equals", "contains", "glob"])
    def test_supported_ops_dont_raise(self, op: str) -> None:
        patterns = [Pattern(field="entity_id", op=op, value="light.*", domain="home")]
        record = {"entity_id": "light.kitchen"}
        # No assertion on result — just confirming no exception path
        compute_domain_hint(record, patterns, _ha_projector)
