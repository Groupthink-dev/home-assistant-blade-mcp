"""Home Assistant Blade MCP Server — entities, control, automations, history, energy, multi-site.

Wraps the Home Assistant REST and WebSocket APIs as MCP tools. Token-efficient
by default: compact pipe-delimited output, null-field omission, field selection.
Write operations gated by HA_WRITE_ENABLED. Security-sensitive operations
(locks, alarms, deletions) require explicit confirm=true.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

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
    """List all areas with floor assignment and aliases. Uses WebSocket registry."""
    try:
        results = await _get_client().list_areas(instance)
        return format_areas(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_devices(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    manufacturer: Annotated[str | None, Field(description="Filter by manufacturer name")] = None,
    limit: Annotated[int, Field(description="Max results")] = 100,
) -> str:
    """List devices, optionally filtered by area or manufacturer. Uses WebSocket registry."""
    try:
        results = await _get_client().list_devices(instance, area, manufacturer, limit)
        return format_devices(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_entities(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    domain: Annotated[str | None, Field(description="Filter by domain (e.g. light, sensor)")] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    label: Annotated[str | None, Field(description="Filter by label")] = None,
    limit: Annotated[int, Field(description="Max results")] = 100,
) -> str:
    """List entities from the registry with metadata (area, device, platform, labels). Uses WebSocket."""
    try:
        results = await _get_client().list_entities_registry(instance, domain, area, label, limit)
        return format_entity_registry(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_floors(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """List floors with their level and icon. Uses WebSocket registry."""
    try:
        results = await _get_client().list_floors(instance)
        return format_floors(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_labels(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
) -> str:
    """List all labels with color and description. Uses WebSocket registry."""
    try:
        results = await _get_client().list_labels(instance)
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
    """Find related entities, devices, areas, and automations for a given item. Graph traversal."""
    try:
        results = await _get_client().search_related(item_type, item_id, instance)
        return format_search_related(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_services_list(
    instance: Annotated[str | None, Field(description="Target HA instance (omit for all)")] = None,
    domain: Annotated[str | None, Field(description="Filter to a specific domain")] = None,
) -> str:
    """List available service domains and their services. Use domain= to filter."""
    try:
        results = await _get_client().list_services(instance, domain)
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
    """Get states for multiple entities in one call. More efficient than repeated ha_state calls."""
    try:
        results = await _get_client().get_states(entity_ids, instance)
        return format_states_grouped(results, fields)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_states_by_domain(
    domain: Annotated[str, Field(description="Entity domain (e.g. light, sensor, climate)")],
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    area: Annotated[str | None, Field(description="Filter by area_id")] = None,
    fields: Annotated[list[str] | None, Field(description="Specific attributes to include")] = None,
    limit: Annotated[int, Field(description="Max results")] = DEFAULT_LIMIT,
) -> str:
    """Get all entity states in a domain (e.g. all lights, all sensors). Optional area filter."""
    try:
        results = await _get_client().get_states_by_domain(domain, instance, area, limit)
        return format_states_grouped(results, fields)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_history(
    entity_ids: Annotated[list[str], Field(description="Entity IDs to query history for")],
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    minimal: Annotated[bool, Field(description="Minimal response (state changes only)")] = True,
) -> str:
    """State change history for entities in a time range. Use minimal=true (default) for token efficiency."""
    try:
        results = await _get_client().get_history(entity_ids, start, end, instance, minimal)
        return format_history(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_logbook(
    start: Annotated[str, Field(description="Start time (ISO 8601)")],
    end: Annotated[str | None, Field(description="End time (ISO 8601, default: now)")] = None,
    entity_id: Annotated[str | None, Field(description="Filter by entity")] = None,
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    limit: Annotated[int, Field(description="Max entries")] = DEFAULT_LIMIT,
) -> str:
    """Logbook entries for a time range. Human-readable event descriptions."""
    try:
        results = await _get_client().get_logbook(start, end, entity_id, instance, limit)
        return format_logbook(results)
    except HAError as e:
        return _error(e)


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
) -> str:
    """Recorder statistics (pre-aggregated). More efficient than raw ha_history for trends."""
    try:
        results = await _get_client().get_statistics(entity_ids, start, end, period, types, instance)
        return format_statistics(results)
    except HAError as e:
        return _error(e)


@mcp.tool()
async def ha_statistics_list(
    instance: Annotated[str | None, Field(description="Target HA instance")] = None,
    statistic_type: Annotated[str | None, Field(description="Filter: mean or sum")] = None,
) -> str:
    """List available statistic IDs and their metadata. Discover what can be queried with ha_statistics."""
    try:
        results = await _get_client().list_statistic_ids(instance, statistic_type)
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
    try:
        results = await _get_client().get_calendar_events(entity_id, start, end, instance)
        return format_calendar_events(results)
    except HAError as e:
        return _error(e)


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
    """List all automations with state (on/off) and last triggered time."""
    try:
        results = await _get_client().list_automations(instance, limit)
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
