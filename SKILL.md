# Home Assistant Blade MCP — LLM Skill Guide

## Token Efficiency Rules (MANDATORY)

1. **Use `ha_states` for batch reads** — single call returns N entities. Never loop `ha_state` per-entity.
2. **Use `ha_states_by_domain` for domain sweeps** — one call for "all lights" or "all sensors in kitchen".
3. **Use `ha_entities` to discover first, then `ha_states` to read** — registry lookup is cheaper than full state dump.
4. **Use `ha_search` for topology** — "what's in this area?" costs 1 call, not N.
5. **Use `ha_statistics` for trends** — pre-aggregated hourly/daily means, not raw `ha_history`.
6. **Use `ha_template` for complex queries** — let HA's Jinja2 engine filter server-side.
7. **Use `fields` parameter** — strip unneeded attributes from state responses.
8. **Prefer convenience tools** — `ha_light` validates brightness; `ha_call_service` does not.
9. **Always pass `instance`** when the user has specified a site.
10. **Use `minimal=true`** (default) for `ha_history` — state changes only, not attribute snapshots.

## Quick Start — 5 Most Common Operations

```
ha_info                                    # Connection status, version, write gate
ha_states_by_domain domain="light"         # All lights across all instances
ha_state entity_id="sensor.outdoor_temp"   # Single entity with smart attribute defaults
ha_areas                                   # Room topology
ha_automations                             # All automations with status
```

## Tool Reference

### Read Tools (22) — no gate required

| Tool | Purpose | Best for |
|------|---------|----------|
| `ha_info` | Health check, version, write gate status | Session start |
| `ha_config` | Location, units, timezone, component count | Context gathering |
| `ha_error_log` | Recent error log lines | Debugging |
| `ha_areas` | All areas with floor assignments | Topology discovery |
| `ha_devices` | Devices by area/manufacturer | Device inventory |
| `ha_entities` | Entity registry (area, device, platform, labels) | Discovery, filtering |
| `ha_floors` | Floor definitions | Multi-story homes |
| `ha_labels` | All labels with colours | Organisation |
| `ha_search` | Related items graph traversal | "What's connected to X?" |
| `ha_services_list` | Available services by domain | Finding capabilities |
| `ha_state` | Single entity state + attributes | Targeted reads |
| `ha_states` | Batch entity states | Multiple specific entities |
| `ha_states_by_domain` | All entities in a domain | Domain sweeps |
| `ha_history` | State change history | Trend analysis |
| `ha_logbook` | Human-readable event log | Activity review |
| `ha_statistics` | Pre-aggregated stats (mean/min/max/sum) | Energy, long-term trends |
| `ha_statistics_list` | Available statistic IDs | Discover what's tracked |
| `ha_calendar_events` | HA calendar events in range | Schedule queries |
| `ha_automations` | All automations with state | Automation review |
| `ha_automation_get` | Full automation YAML config | Editing automations |
| `ha_template` | Jinja2 server-side rendering | Complex queries |
| `ha_camera_snapshot` | Camera proxy URL | Security checks |

### Write Tools (11) — require HA_WRITE_ENABLED=true

| Tool | Purpose | Gate |
|------|---------|------|
| `ha_call_service` | Generic service call | write |
| `ha_light` | Light control (on/off/brightness/color) | write |
| `ha_climate` | HVAC control (mode/temp/fan/preset) | write |
| `ha_scene` | Activate scene | write |
| `ha_automation_trigger` | Manually trigger automation | write |
| `ha_automation_toggle` | Enable/disable automation | write |
| `ha_automation_create` | Create automation from config | write |
| `ha_script_run` | Run script with variables | write |
| `ha_webhook` | Fire HA webhook | write |
| `ha_notify` | Send notification | write |
| `ha_events` | Poll recent events | read |

### Confirm-Gated Tools (3) — require write + confirm=true

| Tool | Purpose | Why gated |
|------|---------|-----------|
| `ha_lock` | Lock/unlock doors | Physical security |
| `ha_alarm` | Arm/disarm alarm panels | Physical security |
| `ha_automation_delete` | Delete automation | Irreversible |

## Workflow Examples

### Morning status check
```
ha_info
ha_states_by_domain domain="sensor" area="living_room" fields=["temperature"]
ha_states_by_domain domain="binary_sensor" fields=["device_class"]
```

### Energy review
```
ha_statistics_list statistic_type="sum"
ha_statistics entity_ids=["sensor.daily_energy"] start="2026-04-01" period="day"
```

### Security audit
```
ha_states_by_domain domain="lock"
ha_states_by_domain domain="binary_sensor" area="entry"
ha_states_by_domain domain="alarm_control_panel"
ha_history entity_ids=["lock.front_door"] start="2026-04-03T00:00:00"
```

### Automation management
```
ha_automations
ha_automation_get automation_id="turn_off_lights_at_midnight"
ha_automation_create automation_id="new_auto" alias="Night Mode" trigger=[...] action=[...]
```

### Multi-site operations
```
ha_info                                              # Status of all sites
ha_states_by_domain domain="climate" instance="sandybay"   # HVAC at Sandy Bay
ha_states_by_domain domain="climate" instance="paddington" # HVAC at Paddington
```

## Security Notes

- Write ops require `HA_WRITE_ENABLED=true` environment variable
- Lock/alarm/delete require explicit `confirm=true` parameter
- Credentials are scrubbed from all error output
- Camera returns proxy URL, not image bytes — never exposes raw image data in tool output
- Bearer tokens are never included in tool responses
