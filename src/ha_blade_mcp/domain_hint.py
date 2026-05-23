"""Per-record domain-hint computation for DD-338 A.2.dom.c.

Loads user-defined pattern rules from a YAML config file (managed by
Stallari's BladeConfigStore) and computes a `domain:` attribution for each
record returned by per-record tools. The result is folded into the
`_meta.domain_hints` map so the dispatcher can partition multi-record
results across domain-bounded inference policies (DD-341).

Convention #22 (migration resilience) — missing/malformed config returns
empty patterns and never raises. Convention #19 (no phone-home) — file
reads only.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class Pattern:
    """One user-defined attribution rule.

    `op` MUST be one of {"equals", "contains", "glob"}. Unknown ops are
    treated as never-matching (defensive — config may be authored by hand
    or by future UI revisions).
    """

    field: str
    op: str
    value: str
    domain: str


def _matches(projected: Any, op: str, value: str) -> bool:
    """Apply one op against one projected field value.

    List-valued projected fields are iterated element-wise; any element
    match wins. `None` never matches.
    """
    if projected is None:
        return False
    if isinstance(projected, list):
        return any(_matches(elem, op, value) for elem in projected)
    s = str(projected)
    if op == "equals":
        return s == value
    if op == "contains":
        return value in s
    if op == "glob":
        return fnmatch.fnmatchcase(s, value)
    return False


def compute_domain_hint(
    record: dict[str, Any],
    patterns: list[Pattern],
    field_projector: Callable[[dict[str, Any], str], Any],
) -> str | None:
    """Compute the first-matching domain attribution for one record.

    First-match-wins by pattern list order. Returns None when no pattern
    matches (caller MUST omit the record from the `_meta.domain_hints`
    map rather than emit a null sentinel).
    """
    for pattern in patterns:
        projected = field_projector(record, pattern.field)
        if _matches(projected, pattern.op, pattern.value):
            return pattern.domain
    return None


def load_patterns_from_yaml(yaml_str: str) -> list[Pattern]:
    """Parse a `patterns:` YAML list into Pattern records.

    Expected shape:

        patterns:
          - {field: friendly_name, op: contains, value: Kitchen, domain: home}
          - {field: entity_namespace, op: equals, value: alarm_control_panel, domain: home}

    Missing / malformed / non-list-shaped input returns []. Per-entry
    missing keys are skipped (not raised) so a partial config still
    yields the valid subset.
    """
    try:
        loaded = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        return []
    if not isinstance(loaded, dict):
        return []
    raw = loaded.get("patterns")
    if not isinstance(raw, list):
        return []
    out: list[Pattern] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(
                Pattern(
                    field=str(entry["field"]),
                    op=str(entry["op"]),
                    value=str(entry["value"]),
                    domain=str(entry["domain"]),
                )
            )
        except (KeyError, TypeError):
            continue
    return out
