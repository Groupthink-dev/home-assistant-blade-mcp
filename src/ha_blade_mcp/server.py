"""Home Assistant Blade MCP Server — entities, control, automations, history, energy, multi-site.

Wraps the Home Assistant REST and WebSocket APIs as MCP tools. Token-efficient
by default: compact pipe-delimited output, null-field omission, field selection.
Write operations gated by HA_WRITE_ENABLED. Security-sensitive operations
(locks, alarms, deletions) require explicit confirm=true.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field
from stallari_mcp_helpers import (
    Pattern,
    load_patterns_from_yaml,
)
from stallari_mcp_helpers import (
    compute_domain_hint as _canonical_compute_domain_hint,
)

from ha_blade_mcp.client import HAClient, HAError
from ha_blade_mcp.formatters import (
    format_areas,
    format_automations,
    format_calendar_events,
    format_config,
    format_devices,
    format_entity_registry,
    format_entity_state,
    format_error_log,
    format_floors,
    format_history,
    format_info,
    format_labels,
    format_logbook,
    format_search_related,
    format_service_result,
    format_services,
    format_states_grouped,
    format_statistic_ids,
    format_statistics,
    format_template_result,
)
from ha_blade_mcp.models import (
    DEFAULT_LIMIT,
    require_confirm,
    require_write,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transport configuration
# ---------------------------------------------------------------------------

TRANSPORT = os.environ.get("HA_MCP_TRANSPORT", "stdio")
HTTP_HOST = os.environ.get("HA_MCP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("HA_MCP_PORT", "8766"))

# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "HomeAssistantBlade",
    instructions=(
        "Home Assistant operations across one or more instances. "
        "Read entity states, control devices, manage automations, query history and energy stats. "
        "Multi-site: pass instance= to target a specific HA instance. "
        "Write operations require HA_WRITE_ENABLED=true. "
        "Security-sensitive operations (locks, alarms, deletions) require confirm=true."
    ),
)

# Lazy-initialized client
_client: HAClient | None = None


def _get_client() -> HAClient:
    """Get or create the HAClient singleton."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = HAClient()
    return _client


def _error(e: HAError) -> str:
    """Format a client error as a user-friendly string."""
    return f"Error: {e}"


# ---------------------------------------------------------------------------
# DD-338 A.2.dom.c — per-record domain_hint computation
# ---------------------------------------------------------------------------
# Reader of the Stallari BladeConfigStore contract (Convention #23). User
# defines patterns via the DomainConsentView UI; they land at
# `<state-root>/blade-config/home-assistant-blade-mcp/config.yaml`. Missing
# or malformed config ⇒ empty pattern list (Convention #22). Never raises
# at module load; the cached `_PATTERNS` list is consulted on every
# per-record tool invocation but recomputed only on server restart (the
# config is rewritten through BladeConfigStore which itself signals the
# daemon to relaunch the blade, so a fresh exec picks up the new shape).

_BLADE_ID = "home-assistant-blade-mcp"


def _state_root() -> str:
    """Resolve the Stallari Application Support state root.

    Honours `STALLARI_STATE_ROOT` (set by the test harness + the daemon
    when running under a non-default profile) and otherwise resolves to
    the macOS default at `~/Library/Application Support/Stallari/`.
    """
    override = os.environ.get("STALLARI_STATE_ROOT")
    if override:
        return override
    return os.path.expanduser("~/Library/Application Support/Stallari")


def _load_blade_config(blade_id: str) -> list[Pattern]:
    """Load user-defined domain-hint patterns for this blade.

    Resolution: `<state-root>/blade-config/<sanitized-blade-id>/config.yaml`.
    Sanitisation lowercases and replaces `/` with `_` so a future scoped
    blade id (e.g. `org/home-assistant-blade-mcp`) maps to a flat dir.
    Missing file / I/O error / malformed YAML ⇒ [].
    """
    sanitized = blade_id.lower().replace("/", "_")
    path = os.path.join(_state_root(), "blade-config", sanitized, "config.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            patterns: list[Pattern] = load_patterns_from_yaml(fh.read())
            return patterns
    except (OSError, ValueError):
        return []


# Cached at module load. A blade restart (triggered when the user saves
# patterns through DomainConsentView) re-executes this module and rebuilds
# the cache.
_PATTERNS: list[Pattern] = _load_blade_config(_BLADE_ID)


def _field_projector(record: dict[str, Any], field: str) -> Any:
    """Project a logical field name to a value out of an HA record.

    Covers the per-record shapes returned by `ha_devices`, `ha_entities`,
    `ha_states_by_domain`, and `ha_statistics`. The four tools mix
    REST-shaped state records (`entity_id`/`state`/`attributes.*`) and
    WebSocket-shaped registry records (`id`/`name`/`area_id`/`labels`).
    Patterns are authored against logical names; the projector hides
    the shape difference.

    Synthesised fields:
        entity_namespace — first segment of entity_id (`light` from
        `light.kitchen`). Useful for "all sensors are home" rules.

    Returns None for unknown fields or missing keys so
    `compute_domain_hint` can short-circuit cleanly.
    """
    if field == "entity_id":
        return record.get("entity_id") or record.get("id")
    if field == "entity_namespace":
        eid = record.get("entity_id")
        if isinstance(eid, str) and "." in eid:
            return eid.split(".", 1)[0]
        return None
    if field == "friendly_name":
        attrs = record.get("attributes")
        if isinstance(attrs, dict):
            return attrs.get("friendly_name")
        # Registry records carry name on the top level
        return record.get("name") or record.get("name_by_user") or record.get("original_name")
    if field == "area_id":
        attrs = record.get("attributes")
        if isinstance(attrs, dict) and attrs.get("area_id") is not None:
            return attrs.get("area_id")
        return record.get("area_id")
    if field == "state":
        return record.get("state")
    if field == "labels":
        return record.get("labels")
    if field == "manufacturer":
        return record.get("manufacturer")
    if field == "model":
        return record.get("model")
    if field == "platform":
        return record.get("platform")
    if field == "domain":
        # `domain` for registry entries is encoded inside entity_id
        eid = record.get("entity_id")
        if isinstance(eid, str) and "." in eid:
            return eid.split(".", 1)[0]
        return None
    return None


def _record_id(record: dict[str, Any]) -> str | None:
    """Pick the canonical record identifier for the _meta.domain_hints map.

    Per spec: HA canonical id is `entity_id`. Registry devices use `id`.
    Returns None when neither is present (record is excluded from the map).
    """
    eid = record.get("entity_id")
    if isinstance(eid, str):
        return eid
    rid = record.get("id")
    if isinstance(rid, str):
        return rid
    return None


def _project_record(record: dict[str, Any], patterns: list[Pattern]) -> dict[str, Any]:
    """Build a flat projection dict consumable by the canonical
    ``compute_domain_hint`` (dot-path resolution).

    The canonical helper resolves pattern fields via plain dot-path lookup
    against the record. HA's record shapes are heterogeneous (REST state
    vs WebSocket registry) AND HA patterns use synthesised fields
    (``entity_namespace`` from ``entity_id``). We pre-project the values
    that the patterns ask for and seed them as top-level keys on a copy
    of the record so canonical sees a uniform shape. Untouched fields on
    the original record pass through unchanged.
    """
    projected = dict(record)
    seen: set[str] = set()
    for pattern in patterns:
        field = pattern.field
        if field in seen:
            continue
        seen.add(field)
        # Skip dotted patterns — caller authored a literal dot-path; let
        # canonical resolve it against the unmodified record.
        if "." in field:
            continue
        value = _field_projector(record, field)
        if value is not None:
            projected[field] = value
    return projected


def compute_domain_hint(
    record: dict[str, Any],
    patterns: list[Pattern],
    field_projector: Callable[[dict[str, Any], str], Any],
) -> str | None:
    """HA-specific wrapper around the canonical ``compute_domain_hint``.

    Bridges the canonical dot-path field-resolution model to HA's
    record-shape projector. Authored against the same three-arg shape the
    blade has used since DD-338 A.2.dom.c so existing tests + callers
    don't change.
    """
    if not patterns:
        return None
    projected = _project_record(record, patterns)
    # field_projector is still consulted indirectly via _project_record
    # above (it captures _field_projector by closure when called from
    # _domain_hints_for). The arg is preserved on the public signature so
    # the test suite + future call-sites can pass a custom projector.
    _ = field_projector  # acknowledged; closure-captured at the call site
    result: str | None = _canonical_compute_domain_hint(projected, patterns)
    return result


def _domain_hints_for(records: list[dict[str, Any]]) -> dict[str, str]:
    """Compute the `_meta.domain_hints` map for a record list.

    Records with no matching pattern OR no resolvable record id are
    omitted from the map. Empty result ⇒ caller MUST omit the
    `domain_hints` key from the meta dict.
    """
    if not _PATTERNS:
        return {}
    out: dict[str, str] = {}
    for record in records:
        rid = _record_id(record)
        if rid is None:
            continue
        hint = compute_domain_hint(record, _PATTERNS, _field_projector)
        if hint is not None:
            out[rid] = hint
    return out


# ---------------------------------------------------------------------------
# DD-338 / DD-278 scope-tag handling (HA-as-one-scope)
# ---------------------------------------------------------------------------
# HA structurally models a single household / building; only home-shaped
# scopes are semantically honest. The relevant cross-household partitioning
# lives at the instance= level (multi-site HA_PROVIDERS), not the scope= tag.

# Scopes that pass through as audit-surfaced no-ops:
_SCOPE_NOOP = {"home", "family", "personal"}

# Scopes that semantically don't apply to HA — reject with an honest error
# rather than silently over-fetch. Mirrors directives/vault-reference.md §3a.
_SCOPE_NOT_APPLICABLE = {
    "work",
    "family-office",
    "trustee-corporate",
    "funds-investment",
    "private-equity",
    "algo-trading",
    "infrastructure",
    "groupthink-dev",
    "school-education",
    "side-hustle",
    "family-people",
    "family-education",
    "family-extended",
    "personal-services",
    # property-* (all enumerated)
    "property-sandy-bay",
    "property-mountain-river",
    "property-cascade-st",
    "property-elizabeth-st",
    "property-battery-point",
    "property-hopetoun-ave",
    "property-robertson",
    "property-kensington-court",
}


def _scope_check(scope: str | None) -> str | None:
    """Validate a DD-278 scope tag against HA's one-scope model.

    Returns:
        None — accept (no-op pass-through). Caller proceeds.
        str  — error message. Caller short-circuits with this as the response.

    Unknown values pass-through with implicit accept (defensive — DD-278
    vocabulary may grow). Property-* prefixes are enumerated explicitly
    rather than prefix-matched to keep the rejection contract honest.
    """
    if scope is None:
        return None
    if scope in _SCOPE_NOT_APPLICABLE:
        return (
            f"Error: scope={scope} not applicable to home-assistant tools "
            f"(HA models a single household; use instance= for multi-site partitioning)"
        )
    return None  # home/family/personal or unrecognised — accept


def _scope_audit_label(scope: str | None) -> str | None:
    """Return the audit label for a scope, or None when scope is unset."""
    if scope is None:
        return None
    if scope in _SCOPE_NOOP:
        return f"scope={scope}"
    # Unknown/unrecognised value — log it but pass through
    return f"scope={scope} (unrecognised, treated as no-op)"


# ===========================================================================
# DOMAIN 1: META (3 tools)
# ===========================================================================


@mcp.tool()
async def ha_info(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """Health check: instances, connection status, HA version, component count, write gate status."""
    try:
        results = await _get_client().info(instance)
        from ha_blade_mcp.models import is_write_enabled

        output = format_info(results)
        output += f"\nwrite_gate={'enabled' if is_write_enabled() else 'disabled'}"
        return output
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_config(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """HA configuration: location, units, elevation, currency, time zone, component count."""
    try:
        results = await _get_client().config(instance)
        return format_config(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_error_log(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    lines: Annotated[int, Field(description="Number of recent log lines")] = 50,
) -> str:
    """Recent error log entries from Home Assistant."""
    try:
        results = await _get_client().error_log(instance, lines)
        return format_error_log(results)
    except HAError as e:
        return _error(e)


# ===========================================================================
# DOMAIN 2: REGISTRY — TOPOLOGY (7 tools)
# ===========================================================================


@mcp.tool()
async def ha_areas(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """List all areas with floor assignment and aliases. Uses WebSocket registry. Sorted by area_id ascending."""
    try:
        results = await _get_client().list_areas(instance)
        # DD-338 B.1.b: canonical sort-before-return on area_id ascending.
        results = sorted(results, key=lambda a: a.get("area_id", "") or "")
        return format_areas(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_devices(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    scope: Annotated[
        str | None,
        Field(description="DD-278 scope tag — home/family/personal accepted; out-of-vocab rejected"),
    ] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    manufacturer: Annotated[str | None, Field(description="Filter by manufacturer name")] = None,
    limit: Annotated[int, Field(description="Max results")] = 100,
) -> str:
    """List devices, optionally filtered by area or manufacturer. Uses WebSocket registry."""
    rejection = _scope_check(scope)
    if rejection:
        return rejection
    t0 = time.perf_counter()
    try:
        records, matched_total = await _get_client().list_devices(instance, area, manufacturer, limit)
    except HAError as e:
        return _error(e)
    # DD-338 B.1.b: canonical sort-before-return on device id ascending.
    records = sorted(records, key=lambda d: d.get("id", "") or "")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    filtered_by: list[str] = []
    scope_label = _scope_audit_label(scope)
    if scope_label:
        filtered_by.append(scope_label)
    if area:
        filtered_by.append(f"area={area}")
    if manufacturer:
        filtered_by.append(f"manufacturer={manufacturer}")
    meta: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": len(records),
        "filtered_by": filtered_by,
        "latency_ms": latency_ms,
    }
    hints = _domain_hints_for(records)
    if hints:
        meta["domain_hints"] = hints
    return format_devices(records, meta=meta)


@mcp.tool()
async def ha_entities(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    scope: Annotated[
        str | None,
        Field(description="DD-278 scope tag — home/family/personal accepted; out-of-vocab rejected"),
    ] = None,
    domain: Annotated[str | None, Field(description="Filter by domain (e.g. light, sensor)")] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    label: Annotated[str | None, Field(description="Filter by label")] = None,
    limit: Annotated[int, Field(description="Max results")] = 100,
) -> str:
    """List entities from the registry with metadata (area, device, platform, labels). Uses WebSocket."""
    rejection = _scope_check(scope)
    if rejection:
        return rejection
    t0 = time.perf_counter()
    try:
        records, matched_total = await _get_client().list_entities_registry(instance, domain, area, label, limit)
    except HAError as e:
        return _error(e)
    # DD-338 B.1.b: canonical sort-before-return on entity_id ascending.
    records = sorted(records, key=lambda e: e.get("entity_id", "") or "")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    filtered_by: list[str] = []
    scope_label = _scope_audit_label(scope)
    if scope_label:
        filtered_by.append(scope_label)
    if domain:
        filtered_by.append(f"domain={domain}")
    if area:
        filtered_by.append(f"area={area}")
    if label:
        filtered_by.append(f"label={label}")
    meta: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": len(records),
        "filtered_by": filtered_by,
        "latency_ms": latency_ms,
    }
    hints = _domain_hints_for(records)
    if hints:
        meta["domain_hints"] = hints
    return format_entity_registry(records, meta=meta)


@mcp.tool()
async def ha_floors(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """List floors with their level and icon. Uses WebSocket registry. Sorted by floor_id ascending."""
    try:
        results = await _get_client().list_floors(instance)
        # DD-338 B.1.b: canonical sort-before-return on floor_id ascending.
        results = sorted(results, key=lambda f: f.get("floor_id", "") or "")
        return format_floors(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_labels(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """List all labels with color and description. Uses WebSocket registry. Sorted by label_id ascending."""
    try:
        results = await _get_client().list_labels(instance)
        # DD-338 B.1.b: canonical sort-before-return on label_id ascending.
        results = sorted(results, key=lambda lb: lb.get("label_id", "") or "")
        return format_labels(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_search(
    item_type: Annotated[
        str,
        Field(description="Type to search from: entity, device, area, automation, script, scene"),
    ],
    item_id: Annotated[str, Field(description="ID of the item to find relations for")],
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """Find related entities, devices, areas, and automations for a given item. Graph traversal.
    Outer item-type traversal preserves upstream relevance order; each per-item-type list is sorted ascending."""
    t0 = time.perf_counter()
    try:
        results = await _get_client().search_related(item_type, item_id, instance)
    except HAError as e:
        return _error(e)
    # DD-338 B.1.b: sort inner per-item-type lists ascending while preserving
    # the outer item-type iteration order (relevance signal from upstream).
    for r in results:
        for k in list(r.keys()):
            if k.startswith("_"):
                continue
            v = r.get(k)
            if isinstance(v, list):
                r[k] = sorted(v, key=lambda x: str(x) if x is not None else "")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # DD-338 Phase C Wave 2: structured audit envelope. The HA /api/search/related
    # endpoint returns only the related-graph for the (item_type, item_id) seed;
    # all discrimination is server-side. matched_total = returned (the upstream
    # endpoint is a point query — no over-fetch + post-filter).
    total_records = sum(
        len(v) if isinstance(v, list) else 0 for r in results for k, v in r.items() if not k.startswith("_")
    )
    meta: dict[str, Any] = {
        "matched_total": total_records,
        "returned": total_records,
        "filtered_by": [f"item_type={item_type}", f"item_id={item_id}"],
        "latency_ms": latency_ms,
    }
    return format_search_related(results, meta=meta)


@mcp.tool()
async def ha_services_list(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    domain: Annotated[str | None, Field(description="Filter to a specific domain")] = None,
) -> str:
    """List available service domains and their services. Use domain= to filter.
    Deterministic ordering: domains sorted ascending, service names sorted ascending (upheld by format_services)."""
    try:
        results = await _get_client().list_services(instance, domain)
        # DD-338 B.1.b: deterministic ordering upheld by format_services
        # (sorts svc_domain entries on `domain` ascending; service names sorted ascending).
        return format_services(results, domain)
    except HAError as e:
        return _error(e)


# ===========================================================================
# DOMAIN 3: STATE (5 tools)
# ===========================================================================


@mcp.tool()
async def ha_state(
    entity_id: Annotated[str, Field(description="Entity ID (e.g. light.living_room)")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    fields: Annotated[
        list[str] | None, Field(description="Specific attributes to include (omit for smart defaults)")
    ] = None,
) -> str:
    """Get current state and attributes of a single entity."""
    try:
        result = await _get_client().get_state(entity_id, instance)
        return format_entity_state(result, fields)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_states(
    entity_ids: Annotated[list[str], Field(description="List of entity IDs")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    fields: Annotated[list[str] | None, Field(description="Specific attributes to include")] = None,
) -> str:
    """Get states for multiple entities in one call. More efficient than repeated ha_state calls.
    Returned entities sorted by entity_id ascending (also upheld by format_entity_list)."""
    t0 = time.perf_counter()
    try:
        results = await _get_client().get_states(entity_ids, instance)
    except HAError as e:
        return _error(e)
    # DD-338 B.1.b: canonical sort-before-return on entity_id ascending.
    # format_entity_list ALSO sorts internally — handler-level sort lifts the
    # contract from a presentation-layer accident to an auditable invariant.
    results = sorted(results, key=lambda r: r.get("entity_id", "") or "")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # DD-338 Phase C Wave 2: entity_ids IS server-side discrimination on the
    # record set; matched_total = len(entity_ids) (the requested set), returned
    # = len(results) (HA-returned subset). Missing IDs surface as redactions.
    returned_ids = {r.get("entity_id", "") for r in results}
    missing = [eid for eid in entity_ids if eid not in returned_ids]
    meta: dict[str, Any] = {
        "matched_total": len(entity_ids),
        "returned": len(results),
        "filtered_by": [f"entity_ids={len(entity_ids)}"],
        "latency_ms": latency_ms,
    }
    if missing:
        meta["redactions"] = [f"entity_id={eid}_not_found" for eid in missing]
    return format_states_grouped(results, fields, meta=meta)


@mcp.tool()
async def ha_states_by_domain(
    domain: Annotated[str, Field(description="Entity domain (e.g. light, sensor, climate)")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    scope: Annotated[
        str | None,
        Field(description="DD-278 scope tag — home/family/personal accepted; out-of-vocab rejected"),
    ] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    fields: Annotated[list[str] | None, Field(description="Specific attributes to include")] = None,
    limit: Annotated[int, Field(description="Max results")] = DEFAULT_LIMIT,
) -> str:
    """Get all entity states in a domain (e.g. all lights, all sensors). Optional area filter."""
    rejection = _scope_check(scope)
    if rejection:
        return rejection
    t0 = time.perf_counter()
    try:
        records, matched_total = await _get_client().get_states_by_domain(domain, instance, area, limit)
    except HAError as e:
        return _error(e)
    # DD-338 B.1.b: canonical sort-before-return on entity_id ascending.
    records = sorted(records, key=lambda e: e.get("entity_id", "") or "")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    filtered_by: list[str] = []
    scope_label = _scope_audit_label(scope)
    if scope_label:
        filtered_by.append(scope_label)
    filtered_by.append(f"domain={domain}")
    if area:
        filtered_by.append(f"area={area}")
    meta: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": len(records),
        "filtered_by": filtered_by,
        "latency_ms": latency_ms,
    }
    hints = _domain_hints_for(records)
    if hints:
        meta["domain_hints"] = hints
    return format_states_grouped(records, fields, meta=meta)


@mcp.tool()
async def ha_history(
    entity_ids: Annotated[list[str], Field(description="Entity IDs to query history for")],
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    minimal: Annotated[bool, Field(description="Minimal response (state changes only)")] = True,
) -> str:
    """State change history for entities in a time range. Use minimal=true (default) for token efficiency."""
    t0 = time.perf_counter()
    try:
        results = await _get_client().get_history(entity_ids, start, end, instance, minimal)
    except HAError as e:
        return _error(e)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # DD-338 Phase C Wave 2: structured envelope. HA applies the time-range +
    # entity filter server-side; matched_total = returned (no over-fetch).
    total_changes = sum(len(eh) for r in results for eh in (r.get("history") or []) if isinstance(eh, list))
    time_range = f"{start}..{end}" if end else f"{start}.."
    meta: dict[str, Any] = {
        "matched_total": total_changes,
        "returned": total_changes,
        "filtered_by": [
            f"entity_ids={len(entity_ids)}",
            f"time_range={time_range}",
            f"minimal={str(minimal).lower()}",
        ],
        "latency_ms": latency_ms,
    }
    return format_history(results, meta=meta)


@mcp.tool()
async def ha_logbook(
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    entity_id: Annotated[str | None, Field(description="Filter by entity")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    limit: Annotated[int, Field(description="Max entries")] = DEFAULT_LIMIT,
) -> str:
    """Logbook entries for a time range. Human-readable event descriptions."""
    t0 = time.perf_counter()
    try:
        results = await _get_client().get_logbook(start, end, entity_id, instance, limit)
    except HAError as e:
        return _error(e)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # DD-338 Phase C Wave 2: HA server applies time-range + entity filter +
    # limit. matched_total == returned (no over-fetch signal available).
    time_range = f"{start}..{end}" if end else f"{start}.."
    filtered_by = [f"time_range={time_range}", f"limit={limit}"]
    if entity_id:
        filtered_by.insert(1, f"entity_id={entity_id}")
    meta: dict[str, Any] = {
        "matched_total": len(results),
        "returned": len(results),
        "filtered_by": filtered_by,
        "latency_ms": latency_ms,
    }
    return format_logbook(results, meta=meta)


# ===========================================================================
# DOMAIN 4: STATISTICS & ENERGY (3 tools)
# ===========================================================================


@mcp.tool()
async def ha_statistics(
    entity_ids: Annotated[list[str], Field(description="Statistic IDs (usually entity IDs)")],
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    period: Annotated[str, Field(description="Aggregation: 5minute, hour, day, week, month")] = "hour",
    types: Annotated[list[str] | None, Field(description="Stat types: mean, min, max, sum, change")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    scope: Annotated[
        str | None,
        Field(description="DD-278 scope tag — home/family/personal accepted; out-of-vocab rejected"),
    ] = None,
) -> str:
    """Recorder statistics (pre-aggregated). More efficient than raw ha_history for trends."""
    rejection = _scope_check(scope)
    if rejection:
        return rejection
    t0 = time.perf_counter()
    try:
        records, matched_total = await _get_client().get_statistics(entity_ids, start, end, period, types, instance)
    except HAError as e:
        return _error(e)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    filtered_by: list[str] = []
    scope_label = _scope_audit_label(scope)
    if scope_label:
        filtered_by.append(scope_label)
    filtered_by.append(f"entity_ids={len(entity_ids)}")
    filtered_by.append(f"period={period}")
    meta: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": matched_total,  # no limit truncation on statistics
        "filtered_by": filtered_by,
        "latency_ms": latency_ms,
    }
    # ha_statistics returns [{instance, statistics: {stat_id: [points]}}].
    # Synthesise a per-stat_id pseudo-record so the same projector +
    # pattern set apply unchanged (stat_id is typically entity-shaped).
    if _PATTERNS:
        stat_records: list[dict[str, Any]] = []
        for r in records:
            stats = r.get("statistics", {})
            if isinstance(stats, dict):
                for stat_id in stats.keys():
                    stat_records.append({"entity_id": stat_id})
        hints = _domain_hints_for(stat_records)
        if hints:
            meta["domain_hints"] = hints
    return format_statistics(records, meta=meta)


@mcp.tool()
async def ha_statistics_list(
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    statistic_type: Annotated[str | None, Field(description="Filter: mean or sum")] = None,
) -> str:
    """List available statistic IDs and their metadata. Discover what can be queried with ha_statistics.
    Sorted by statistic_id ascending."""
    try:
        results = await _get_client().list_statistic_ids(instance, statistic_type)
        # DD-338 B.1.b: canonical sort-before-return on statistic_id ascending.
        results = sorted(results, key=lambda s: s.get("statistic_id", "") or "")
        return format_statistic_ids(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_calendar_events(
    entity_id: Annotated[str, Field(description="Calendar entity ID")],
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str, Field(description="End time (ISO 8601)")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Get events from a Home Assistant calendar entity in a time range."""
    t0 = time.perf_counter()
    try:
        results = await _get_client().get_calendar_events(entity_id, start, end, instance)
    except HAError as e:
        return _error(e)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    # DD-338 Phase C Wave 2: HA applies entity + time-range filter server-side.
    meta: dict[str, Any] = {
        "matched_total": len(results),
        "returned": len(results),
        "filtered_by": [f"entity_id={entity_id}", f"time_range={start}..{end}"],
        "latency_ms": latency_ms,
    }
    return format_calendar_events(results, meta=meta)


# ===========================================================================
# DOMAIN 5: CONTROL — CONVENIENCE (6 tools, write-gated)
# ===========================================================================


@mcp.tool()
async def ha_call_service(
    domain: Annotated[str, Field(description="Service domain (e.g. light, switch, cover)")],
    service: Annotated[str, Field(description="Service name (e.g. turn_on, set_temperature)")],
    target: Annotated[
        dict[str, Any] | None,
        Field(description="Target: {entity_id, device_id, area_id, label_id} (string or list)"),
    ] = None,
    data: Annotated[dict[str, Any] | None, Field(description="Service data parameters")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Generic service call. Covers any HA service domain. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        results = await _get_client().call_service(domain, service, instance, target, data)
        return format_service_result(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_light(
    entity_id: Annotated[str | None, Field(description="Light entity ID")] = None,
    area: Annotated[str | None, Field(description="Target all lights in area")] = None,
    action: Annotated[str, Field(description="on, off, or toggle")] = "on",
    brightness: Annotated[int | None, Field(description="Brightness 0-255")] = None,
    color_temp: Annotated[int | None, Field(description="Color temperature in mireds")] = None,
    rgb_color: Annotated[list[int] | None, Field(description="RGB color [r, g, b]")] = None,
    transition: Annotated[int | None, Field(description="Transition time in seconds")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Control lights: on/off/toggle, brightness, colour, temperature. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    if not entity_id and not area:
        return "Error: Provide entity_id or area"

    target: dict[str, Any] = {}
    if entity_id:
        target["entity_id"] = entity_id
    if area:
        target["area_id"] = area

    svc_data: dict[str, Any] = {}
    if brightness is not None:
        svc_data["brightness"] = max(0, min(255, brightness))
    if color_temp is not None:
        svc_data["color_temp"] = color_temp
    if rgb_color is not None:
        svc_data["rgb_color"] = rgb_color
    if transition is not None:
        svc_data["transition"] = transition

    service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(action, "turn_on")
    try:
        results = await _get_client().call_service("light", service, instance, target, svc_data)
        return format_service_result(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_climate(
    entity_id: Annotated[str | None, Field(description="Climate entity ID")] = None,
    area: Annotated[str | None, Field(description="Target all climate in area")] = None,
    hvac_mode: Annotated[
        str | None, Field(description="HVAC mode: heat, cool, heat_cool, auto, dry, fan_only, off")
    ] = None,
    temperature: Annotated[float | None, Field(description="Target temperature")] = None,
    target_temp_high: Annotated[float | None, Field(description="Upper target for heat_cool")] = None,
    target_temp_low: Annotated[float | None, Field(description="Lower target for heat_cool")] = None,
    fan_mode: Annotated[str | None, Field(description="Fan mode: auto, low, medium, high")] = None,
    preset_mode: Annotated[str | None, Field(description="Preset: away, home, eco, boost")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Control HVAC: mode, temperature, fan, preset. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    if not entity_id and not area:
        return "Error: Provide entity_id or area"

    target: dict[str, Any] = {}
    if entity_id:
        target["entity_id"] = entity_id
    if area:
        target["area_id"] = area

    # Set HVAC mode first if specified
    results_text = []
    if hvac_mode:
        try:
            results = await _get_client().call_service(
                "climate", "set_hvac_mode", instance, target, {"hvac_mode": hvac_mode}
            )
            results_text.append(f"hvac_mode={hvac_mode}: {format_service_result(results)}")
        except HAError as e:
            return _error(e)

    # Set temperature
    svc_data: dict[str, Any] = {}
    if temperature is not None:
        svc_data["temperature"] = temperature
    if target_temp_high is not None:
        svc_data["target_temp_high"] = target_temp_high
    if target_temp_low is not None:
        svc_data["target_temp_low"] = target_temp_low
    if svc_data:
        try:
            results = await _get_client().call_service("climate", "set_temperature", instance, target, svc_data)
            results_text.append(f"temperature: {format_service_result(results)}")
        except HAError as e:
            return _error(e)

    # Set fan mode
    if fan_mode:
        try:
            results = await _get_client().call_service(
                "climate", "set_fan_mode", instance, target, {"fan_mode": fan_mode}
            )
            results_text.append(f"fan_mode={fan_mode}: {format_service_result(results)}")
        except HAError as e:
            return _error(e)

    # Set preset
    if preset_mode:
        try:
            results = await _get_client().call_service(
                "climate", "set_preset_mode", instance, target, {"preset_mode": preset_mode}
            )
            results_text.append(f"preset={preset_mode}: {format_service_result(results)}")
        except HAError as e:
            return _error(e)

    return "\n".join(results_text) if results_text else "No changes requested"


@mcp.tool()
async def ha_scene(
    entity_id: Annotated[str, Field(description="Scene entity ID (e.g. scene.movie_night)")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Activate a scene. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        results = await _get_client().call_service("scene", "turn_on", instance, {"entity_id": entity_id})
        return f"Activated {entity_id}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_lock(
    entity_id: Annotated[str | None, Field(description="Lock entity ID")] = None,
    area: Annotated[str | None, Field(description="Target all locks in area")] = None,
    action: Annotated[str, Field(description="lock, unlock, or open")] = "lock",
    code: Annotated[str | None, Field(description="Lock code if required")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    confirm: Annotated[bool, Field(description="Must be true — security-sensitive operation")] = False,
) -> str:
    """Lock or unlock a door. Security-sensitive: requires HA_WRITE_ENABLED=true AND confirm=true."""
    gate = require_write()
    if gate:
        return gate
    conf = require_confirm(confirm)
    if conf:
        return conf
    if not entity_id and not area:
        return "Error: Provide entity_id or area"

    target: dict[str, Any] = {}
    if entity_id:
        target["entity_id"] = entity_id
    if area:
        target["area_id"] = area

    svc_data: dict[str, Any] = {}
    if code:
        svc_data["code"] = code

    try:
        results = await _get_client().call_service("lock", action, instance, target, svc_data)
        return f"{action}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_alarm(
    entity_id: Annotated[str, Field(description="Alarm control panel entity ID")],
    action: Annotated[str, Field(description="arm_away, arm_home, arm_night, disarm, or trigger")],
    code: Annotated[str | None, Field(description="Alarm code if required")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    confirm: Annotated[bool, Field(description="Must be true — security-sensitive operation")] = False,
) -> str:
    """Arm, disarm, or trigger an alarm panel. Security-sensitive: requires confirm=true."""
    gate = require_write()
    if gate:
        return gate
    conf = require_confirm(confirm)
    if conf:
        return conf

    svc_data: dict[str, Any] = {}
    if code:
        svc_data["code"] = code

    service = f"alarm_{action}"
    try:
        results = await _get_client().call_service(
            "alarm_control_panel", service, instance, {"entity_id": entity_id}, svc_data
        )
        return f"{action}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


# ===========================================================================
# DOMAIN 6: AUTOMATION & CONFIG (8 tools)
# ===========================================================================


@mcp.tool()
async def ha_automations(
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    limit: Annotated[int, Field(description="Max results")] = DEFAULT_LIMIT,
) -> str:
    """List all automations with state (on/off) and last triggered time. Sorted by entity_id ascending."""
    try:
        results = await _get_client().list_automations(instance, limit)
        # DD-338 B.1.b: canonical sort-before-return on entity_id ascending
        # (stable across friendly-name renames; entity_id is the canonical handle).
        results = sorted(results, key=lambda a: a.get("entity_id", "") or "")
        return format_automations(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_automation_get(
    automation_id: Annotated[str, Field(description="Automation ID (from entity_id after 'automation.')")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Get full YAML configuration of an automation by ID."""
    try:
        result = await _get_client().get_automation_config(automation_id, instance)
        # Return as readable YAML-like format
        import json

        return json.dumps(result, indent=2, default=str)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_automation_trigger(
    entity_id: Annotated[str, Field(description="Automation entity ID")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Manually trigger an existing automation. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        results = await _get_client().call_service("automation", "trigger", instance, {"entity_id": entity_id})
        return f"Triggered {entity_id}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_automation_toggle(
    entity_id: Annotated[str, Field(description="Automation entity ID")],
    action: Annotated[str, Field(description="turn_on or turn_off")] = "turn_on",
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Enable or disable an automation. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        results = await _get_client().call_service("automation", action, instance, {"entity_id": entity_id})
        return f"{action} {entity_id}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_automation_create(
    automation_id: Annotated[str, Field(description="Unique ID for the automation")],
    alias: Annotated[str, Field(description="Human-readable name")],
    trigger: Annotated[list[dict[str, Any]], Field(description="Trigger configuration list")],
    action: Annotated[list[dict[str, Any]], Field(description="Action configuration list")],
    description: Annotated[str | None, Field(description="Automation description")] = None,
    condition: Annotated[list[dict[str, Any]] | None, Field(description="Condition list")] = None,
    mode: Annotated[str | None, Field(description="single, restart, queued, parallel")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Create a new automation. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate

    config: dict[str, Any] = {
        "alias": alias,
        "trigger": trigger,
        "action": action,
    }
    if description:
        config["description"] = description
    if condition:
        config["condition"] = condition
    if mode:
        config["mode"] = mode

    try:
        result = await _get_client().create_automation(automation_id, config, instance)
        return f"Created automation {automation_id} on {result['instance']}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_automation_delete(
    automation_id: Annotated[str, Field(description="Automation ID to delete")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    confirm: Annotated[bool, Field(description="Must be true to confirm deletion")] = False,
) -> str:
    """Delete an automation. Destructive: requires HA_WRITE_ENABLED=true AND confirm=true."""
    gate = require_write()
    if gate:
        return gate
    conf = require_confirm(confirm)
    if conf:
        return conf
    try:
        result = await _get_client().delete_automation(automation_id, instance)
        return f"Deleted automation {automation_id} on {result['instance']}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_script_run(
    script_id: Annotated[str, Field(description="Script entity ID or slug")],
    variables: Annotated[dict[str, Any] | None, Field(description="Script variables")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Run a script with optional variables. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        result = await _get_client().run_script(script_id, variables, instance)
        return f"Started script {script_id} on {result['instance']}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_template(
    template: Annotated[str, Field(description="Jinja2 template string")],
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """Render a Jinja2 template server-side. Powerful for complex queries without multiple round trips."""
    try:
        results = await _get_client().render_template(template, instance)
        return format_template_result(results)
    except HAError as e:
        return _error(e)


# ===========================================================================
# DOMAIN 7: DIAGNOSTICS & WEBHOOKS (4 tools)
# ===========================================================================


@mcp.tool()
async def ha_camera_snapshot(
    entity_id: Annotated[str, Field(description="Camera entity ID")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Get camera snapshot URL. Returns authenticated proxy URL, not image bytes (token-efficient)."""
    try:
        result = await _get_client().camera_snapshot_url(entity_id, instance)
        return f"{result['entity_id']} | {result['proxy_url']} | {result['note']}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_webhook(
    webhook_id: Annotated[str, Field(description="Webhook ID registered in HA")],
    data: Annotated[dict[str, Any] | None, Field(description="JSON payload")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Fire a webhook on the HA instance. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate
    try:
        result = await _get_client().fire_webhook(webhook_id, data, instance)
        return f"Webhook {webhook_id} fired on {result['instance']}"
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_events(
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    entity_id: Annotated[str | None, Field(description="Filter by entity")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    limit: Annotated[int, Field(description="Max entries")] = DEFAULT_LIMIT,
) -> str:
    """Recent events from the logbook (poll-based). Alias for ha_logbook with event-oriented framing."""
    try:
        results = await _get_client().get_logbook(start, end, entity_id, instance, limit)
        return format_logbook(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_notify(
    service: Annotated[str, Field(description="Notify service name (e.g. mobile_app_phone)")],
    message: Annotated[str, Field(description="Notification message")],
    title: Annotated[str | None, Field(description="Notification title")] = None,
    data: Annotated[dict[str, Any] | None, Field(description="Extra notification data")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
) -> str:
    """Send a notification via HA notify service. Requires HA_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return gate

    svc_data: dict[str, Any] = {"message": message}
    if title:
        svc_data["title"] = title
    if data:
        svc_data["data"] = data

    try:
        results = await _get_client().call_service("notify", service, instance, data=svc_data)
        return f"Notification sent via {service}: {format_service_result(results)}"
    except HAError as e:
        return _error(e)


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    """Run the MCP server."""
    if TRANSPORT == "http":
        from starlette.middleware import Middleware

        from ha_blade_mcp.auth import BearerAuthMiddleware

        mcp.run(
            transport="streamable-http",
            host=HTTP_HOST,
            port=HTTP_PORT,
            middleware=[Middleware(BearerAuthMiddleware)],
        )
    else:
        mcp.run(transport="stdio")
