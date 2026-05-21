"""Token-efficient output formatters for Home Assistant Blade MCP server.

All formatters return compact strings optimised for LLM consumption:
- One line per entity/event
- Pipe-delimited fields
- Null-field omission
- Grouped by instance when multi-provider
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def _append_meta(body: str, meta: dict[str, Any] | None) -> str:
    """Append a DD-338 _meta envelope as a JSON-tail block after body.

    Wire shape (DD-338 Phase A.1 architect amendment):

        <body>

        _meta: {"matched_total": N, "returned": M, "filtered_by": [...], "latency_ms": X}

    Single line, JSON object, appended after `\\n\\n`. Assembler regex:
    `\\n\\n_meta: (\\{.*\\})$`. Returns body verbatim when meta is None.
    """
    if meta is None:
        return body
    return f"{body}\n\n_meta: {json.dumps(meta, separators=(', ', ': '), ensure_ascii=False)}"


def _pick(data: dict[str, Any], *keys: str) -> list[str]:
    """Extract non-None key=value pairs from a dict."""
    parts = []
    for k in keys:
        v = data.get(k)
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    return parts


def _group_by_instance(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group items by _instance field."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        inst = item.get("_instance", "default")
        groups.setdefault(inst, []).append(item)
    return groups


def _with_instance_header(
    groups: dict[str, list[dict[str, Any]]], formatter: Callable[[list[dict[str, Any]]], str]
) -> str:
    """Apply formatter per group, adding instance headers when multi-instance."""
    if len(groups) == 1:
        key = next(iter(groups))
        return formatter(groups[key])
    lines = []
    for inst, items in groups.items():
        lines.append(f"### {inst}")
        lines.append(formatter(items))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Info / Config
# ---------------------------------------------------------------------------


def format_info(results: list[dict[str, Any]]) -> str:
    """Format ha_info results."""
    if not results:
        return "(no instances configured)"
    lines = []
    for r in results:
        parts = [r.get("instance", "?"), r.get("status", "unknown")]
        if r.get("version"):
            parts.append(f"v{r['version']}")
        if r.get("location_name"):
            parts.append(r["location_name"])
        if r.get("components"):
            parts.append(f"components={r['components']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_config(results: list[dict[str, Any]]) -> str:
    """Format ha_config results."""
    lines = []
    for r in results:
        parts = [r.get("instance", "?")]
        parts.extend(_pick(r, "version", "location_name", "time_zone", "currency", "elevation"))
        if r.get("unit_system"):
            parts.append(f"temp_unit={r['unit_system']}")
        if r.get("components_count"):
            parts.append(f"components={r['components_count']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_error_log(results: list[dict[str, Any]]) -> str:
    """Format ha_error_log results."""
    lines = []
    for r in results:
        inst = r.get("instance", "?")
        log_lines = r.get("lines", [])
        if len(results) > 1:
            lines.append(f"### {inst}")
        if not log_lines:
            lines.append("(no errors)")
        else:
            lines.extend(log_lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entity state
# ---------------------------------------------------------------------------


def format_entity_state(entity: dict[str, Any], fields: list[str] | None = None) -> str:
    """Format a single entity state as a compact one-line string.

    Example: light.living_room | on | brightness=178 | color_temp=350 | area=Living Room
    """
    eid = entity.get("entity_id", "?")
    state = entity.get("state", "unknown")
    parts = [eid, state]

    attrs = entity.get("attributes", {})
    if fields:
        for f in fields:
            v = attrs.get(f)
            if v is not None:
                parts.append(f"{f}={v}")
    else:
        # Auto-select useful attributes based on domain
        domain = eid.split(".")[0] if "." in eid else ""
        if domain == "light":
            parts.extend(_pick(attrs, "brightness", "color_temp", "rgb_color"))
        elif domain == "climate":
            parts.extend(_pick(attrs, "temperature", "current_temperature", "hvac_action", "fan_mode"))
        elif domain == "sensor":
            unit = attrs.get("unit_of_measurement")
            if unit:
                parts[-1] = f"{state} {unit}"
            parts.extend(_pick(attrs, "device_class"))
        elif domain == "binary_sensor":
            parts.extend(_pick(attrs, "device_class"))
        elif domain == "cover":
            parts.extend(_pick(attrs, "current_position"))
        elif domain == "media_player":
            parts.extend(_pick(attrs, "media_title", "source", "volume_level"))
        elif domain == "lock":
            pass  # state is sufficient
        elif domain == "alarm_control_panel":
            pass

        friendly_name = attrs.get("friendly_name")
        if friendly_name and friendly_name != eid:
            parts.append(f"name={friendly_name}")

    return " | ".join(str(p) for p in parts)


def format_entity_list(entities: list[dict[str, Any]], fields: list[str] | None = None) -> str:
    """Format a list of entity states as compact lines, grouped by domain."""
    if not entities:
        return "(no entities)"

    # Group by domain
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        eid = e.get("entity_id", "unknown.unknown")
        domain = eid.split(".")[0]
        by_domain.setdefault(domain, []).append(e)

    lines = []
    for domain in sorted(by_domain.keys()):
        domain_entities = by_domain[domain]
        lines.append(f"## {domain} ({len(domain_entities)})")
        for e in sorted(domain_entities, key=lambda x: x.get("entity_id", "")):
            lines.append(format_entity_state(e, fields))

    return "\n".join(lines)


def format_states_grouped(
    entities: list[dict[str, Any]],
    fields: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    """Format entities grouped by instance, then by domain."""
    groups = _group_by_instance(entities)
    body = _with_instance_header(groups, lambda items: format_entity_list(items, fields))
    return _append_meta(body, meta)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def format_history(results: list[dict[str, Any]]) -> str:
    """Format history results as compact time series."""
    if not results:
        return "(no history)"
    lines = []
    for r in results:
        inst = r.get("instance", "?")
        history = r.get("history", [])
        if len(results) > 1:
            lines.append(f"### {inst}")
        for entity_history in history:
            if not entity_history:
                continue
            eid = entity_history[0].get("entity_id", "?")
            lines.append(f"## {eid}")
            for state in entity_history:
                ts = state.get("last_changed", "?")
                if "T" in ts:
                    ts = ts.split("T")[1][:5]  # HH:MM
                lines.append(f"{ts} | {state.get('state', '?')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Logbook
# ---------------------------------------------------------------------------


def format_logbook(entries: list[dict[str, Any]]) -> str:
    """Format logbook entries as compact lines."""
    if not entries:
        return "(no logbook entries)"
    lines = []
    for e in entries:
        ts = e.get("when", "?")
        if "T" in str(ts):
            ts = str(ts).split("T")[1][:5]
        name = e.get("name", "?")
        message = e.get("message", "")
        entity_id = e.get("entity_id", "")
        parts = [ts, name]
        if message:
            parts.append(message)
        if entity_id:
            parts.append(entity_id)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Areas / Devices / Floors / Labels (registry)
# ---------------------------------------------------------------------------


def format_areas(areas: list[dict[str, Any]]) -> str:
    """Format areas as compact lines."""
    if not areas:
        return "(no areas)"
    groups = _group_by_instance(areas)
    lines = []
    for inst, items in groups.items():
        if len(groups) > 1:
            lines.append(f"### {inst}")
        for a in sorted(items, key=lambda x: x.get("name", "")):
            parts = [a.get("area_id", "?"), a.get("name", "?")]
            parts.extend(_pick(a, "floor_id", "icon"))
            aliases = a.get("aliases", [])
            if aliases:
                parts.append(f"aliases={','.join(aliases)}")
            lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_devices(devices: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    """Format devices as compact lines."""
    if not devices:
        return _append_meta("(no devices)", meta)
    groups = _group_by_instance(devices)
    lines = []
    for inst, items in groups.items():
        if len(groups) > 1:
            lines.append(f"### {inst}")
        for d in sorted(items, key=lambda x: x.get("name", "") or ""):
            parts = [d.get("id", "?")]
            name = d.get("name_by_user") or d.get("name") or "?"
            parts.append(name)
            parts.extend(_pick(d, "manufacturer", "model", "area_id"))
            if d.get("disabled_by"):
                parts.append("DISABLED")
            lines.append(" | ".join(parts))
    return _append_meta("\n".join(lines), meta)


def format_floors(floors: list[dict[str, Any]]) -> str:
    """Format floors as compact lines."""
    if not floors:
        return "(no floors)"
    lines = []
    for f in sorted(floors, key=lambda x: x.get("level", 0) or 0):
        parts = [f.get("floor_id", "?"), f.get("name", "?")]
        parts.extend(_pick(f, "level", "icon"))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def format_labels(labels: list[dict[str, Any]]) -> str:
    """Format labels as compact lines."""
    if not labels:
        return "(no labels)"
    lines = []
    for lb in sorted(labels, key=lambda x: x.get("name", "")):
        parts = [lb.get("label_id", "?"), lb.get("name", "?")]
        parts.extend(_pick(lb, "color", "description"))
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entity registry
# ---------------------------------------------------------------------------


def format_entity_registry(entities: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    """Format entity registry entries as compact lines, grouped by domain."""
    if not entities:
        return _append_meta("(no entities)", meta)
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for e in entities:
        eid = e.get("entity_id", "?.?")
        domain = eid.split(".")[0]
        by_domain.setdefault(domain, []).append(e)

    lines = []
    for domain in sorted(by_domain.keys()):
        items = by_domain[domain]
        lines.append(f"## {domain} ({len(items)})")
        for e in sorted(items, key=lambda x: x.get("entity_id", "")):
            parts = [e.get("entity_id", "?")]
            name = e.get("name") or e.get("original_name") or ""
            if name:
                parts.append(name)
            parts.extend(_pick(e, "area_id", "device_id", "platform"))
            if e.get("disabled_by"):
                parts.append("DISABLED")
            if e.get("hidden_by"):
                parts.append("HIDDEN")
            labels = e.get("labels", [])
            if labels:
                parts.append(f"labels={','.join(labels)}")
            lines.append(" | ".join(parts))
    return _append_meta("\n".join(lines), meta)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def format_services(results: list[dict[str, Any]], domain_filter: str | None = None) -> str:
    """Format service list as compact domain.service lines."""
    if not results:
        return "(no services)"
    lines = []
    for r in results:
        inst = r.get("instance", "?")
        services = r.get("services", [])
        if len(results) > 1:
            lines.append(f"### {inst}")
        for svc_domain in sorted(services, key=lambda x: x.get("domain", "")):
            domain = svc_domain.get("domain", "?")
            svc_list = svc_domain.get("services", {})
            svc_names = sorted(svc_list.keys())
            lines.append(f"{domain}: {' | '.join(svc_names)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Automations / Scripts / Scenes (from states)
# ---------------------------------------------------------------------------


def format_automations(entities: list[dict[str, Any]]) -> str:
    """Format automation states as compact lines."""
    if not entities:
        return "(no automations)"
    lines = []
    for e in sorted(entities, key=lambda x: x.get("attributes", {}).get("friendly_name", "")):
        attrs = e.get("attributes", {})
        parts = [
            e.get("entity_id", "?"),
            e.get("state", "?"),
            attrs.get("friendly_name", ""),
        ]
        last_triggered = attrs.get("last_triggered")
        if last_triggered:
            parts.append(f"last={last_triggered[:16]}")
        mode = attrs.get("mode")
        if mode:
            parts.append(f"mode={mode}")
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calendar events
# ---------------------------------------------------------------------------


def format_calendar_events(events: list[dict[str, Any]]) -> str:
    """Format HA calendar events as compact lines."""
    if not events:
        return "(no events)"
    lines = []
    for e in sorted(events, key=lambda x: x.get("start", {}).get("dateTime", x.get("start", {}).get("date", ""))):
        start = e.get("start", {})
        end = e.get("end", {})
        start_str = start.get("dateTime", start.get("date", "?"))
        end_str = end.get("dateTime", end.get("date", ""))
        if "T" in start_str:
            start_str = start_str.split("T")[1][:5]
        if "T" in end_str:
            end_str = end_str.split("T")[1][:5]
        time_range = f"{start_str}-{end_str}" if end_str else start_str
        summary = e.get("summary", "(untitled)")
        parts = [time_range, summary]
        location = e.get("location")
        if location:
            parts.append(f"location={location}")
        desc = e.get("description")
        if desc:
            parts.append(f"desc={desc[:80]}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def format_statistics(results: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    """Format recorder statistics as compact lines."""
    if not results:
        return _append_meta("(no statistics)", meta)
    lines = []
    for r in results:
        inst = r.get("instance", "?")
        stats = r.get("statistics", {})
        if len(results) > 1:
            lines.append(f"### {inst}")
        for stat_id, data_points in stats.items():
            lines.append(f"## {stat_id}")
            for dp in data_points:
                ts = dp.get("start", "?")
                if "T" in str(ts):
                    ts = str(ts).split("T")[1][:5]
                parts = [ts]
                parts.extend(_pick(dp, "mean", "min", "max", "sum", "change"))
                if not any(k in dp for k in ("mean", "min", "max", "sum", "change")):
                    parts.append(f"state={dp.get('state', '?')}")
                lines.append(" | ".join(str(p) for p in parts))
    return _append_meta("\n".join(lines), meta)


def format_statistic_ids(ids: list[dict[str, Any]]) -> str:
    """Format statistic ID list."""
    if not ids:
        return "(no statistic IDs)"
    lines = []
    for s in sorted(ids, key=lambda x: x.get("statistic_id", "")):
        parts = [s.get("statistic_id", "?")]
        parts.extend(_pick(s, "unit_of_measurement", "source", "statistics_unit_of_measurement"))
        name = s.get("name")
        if name:
            parts.append(name)
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Search related
# ---------------------------------------------------------------------------


def format_search_related(results: list[dict[str, Any]]) -> str:
    """Format search/related results."""
    if not results:
        return "(no results)"
    lines = []
    for r in results:
        inst = r.get("_instance", "?")
        if len(results) > 1:
            lines.append(f"### {inst}")
        for item_type, items in r.items():
            if item_type.startswith("_"):
                continue
            if isinstance(items, list) and items:
                lines.append(f"## {item_type} ({len(items)})")
                for item in items:
                    lines.append(f"  {item}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service call results
# ---------------------------------------------------------------------------


def format_service_result(results: list[dict[str, Any]]) -> str:
    """Format service call results."""
    parts = []
    for r in results:
        inst = r.get("instance", "?")
        changed = r.get("changed_states", 0)
        parts.append(f"{inst}: {changed} state(s) changed")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Generic template result
# ---------------------------------------------------------------------------


def format_template_result(results: list[dict[str, Any]]) -> str:
    """Format template render results."""
    if len(results) == 1:
        return str(results[0].get("result", ""))
    lines = []
    for r in results:
        lines.append(f"### {r.get('instance', '?')}")
        lines.append(str(r.get("result", "")))
    return "\n".join(lines)
