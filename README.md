# Home Assistant Blade MCP

A security-first, token-efficient MCP server for Home Assistant. 36 tools across entity state, device control, automations, history, energy statistics, and multi-site management.

## Why another Home Assistant MCP?

| | Official HA MCP | ha-mcp | hass-mcp | **This** |
|---|---|---|---|---|
| **Tools** | ~8 (intent-only) | 92 (bloated) | 12 (minimal) | 36 (targeted) |
| **Token cost** | Dumps all entities per call | 260KB service listings | No field selection | Pipe-delimited, field-selected |
| **Write safety** | None | Exposes filesystem + YAML | None | Write gate + confirm gate |
| **Multi-instance** | Single only | Single | Single | Native multi-site |
| **Event/webhook** | None | WebSocket client | None | Webhook tools |
| **Credential safety** | N/A | Token in web forms | N/A | Scrubbed from all output |

**The official Home Assistant MCP server** (`home-assistant.io/integrations/mcp_server`) dumps the full state of every entity on every call. It exposes ~8 intent-based tools and cannot query individual entities, areas, or history. Adequate for "turn on the lights" — not for agentic operations.

**ha-mcp** (`homeassistant-ai/ha-mcp`) has 92 tools including filesystem read/write, YAML config editing, and restart — with no write gates. Its `tools/list` response alone exhausts token budgets. The BM25 search transform mitigates this but adds indirection.

**hass-mcp** (`achetronic/hass-mcp`) is lean (12 tools) with strong JWT auth, but too minimal for real automation management and lacks multi-instance support.

**This MCP** is designed for agentic platforms that need:
- **Precise reads** — query one entity, one area, one domain. No full-state dumps.
- **Safe writes** — two-tier gating (env var + per-call confirm) for physical security operations.
- **Multi-site** — manage multiple HA instances from a single MCP server.
- **Token efficiency** — pipe-delimited output, null-field omission, smart attribute defaults per domain.
- **Webhook integration** — fire HA webhooks for event-driven automation dispatch.

## Quick Start

### Install

```bash
# With uv (recommended)
uv tool install home-assistant-blade-mcp

# Or from source
git clone https://github.com/piersdd/home-assistant-blade-mcp.git
cd home-assistant-blade-mcp
make install
```

### Configure

```bash
# Single instance
export HA_URL="http://homeassistant.local:8123"
export HA_TOKEN="your-long-lived-access-token"

# Multi-instance
export HA_PROVIDERS="sandybay,paddington"
export HA_SANDYBAY_URL="http://ha-sb.local:8123"
export HA_SANDYBAY_TOKEN="token-for-sandybay"
export HA_PADDINGTON_URL="http://ha-pad.local:8123"
export HA_PADDINGTON_TOKEN="token-for-paddington"

# Enable device control (disabled by default)
export HA_WRITE_ENABLED="true"
```

Create a Long-Lived Access Token at **Profile > Security > Long-Lived Access Tokens** in your HA instance.

### Run

```bash
# stdio (default — for Claude Code, Claude Desktop)
home-assistant-blade-mcp

# HTTP transport (for remote access)
HA_MCP_TRANSPORT=http HA_MCP_API_TOKEN=your-secret home-assistant-blade-mcp
```

### Claude Code Integration

```json
{
  "mcpServers": {
    "home-assistant": {
      "command": "uvx",
      "args": ["home-assistant-blade-mcp"],
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "your-token",
        "HA_WRITE_ENABLED": "true"
      }
    }
  }
}
```

### Claude Desktop Integration

```json
{
  "mcpServers": {
    "home-assistant": {
      "command": "uvx",
      "args": ["home-assistant-blade-mcp"],
      "env": {
        "HA_URL": "http://homeassistant.local:8123",
        "HA_TOKEN": "your-token"
      }
    }
  }
}
```

## Tools (36)

### Read (22 tools)

| Tool | Description | Token Cost |
|------|-------------|-----------|
| `ha_info` | Connection status, version, write gate | Low |
| `ha_config` | Location, units, timezone | Low |
| `ha_error_log` | Recent error log lines | Medium |
| `ha_areas` | All areas with floor assignment | Low |
| `ha_devices` | Devices by area/manufacturer | Medium |
| `ha_entities` | Entity registry with metadata | Medium |
| `ha_floors` | Floor definitions | Low |
| `ha_labels` | All labels | Low |
| `ha_search` | Related items graph traversal | Low |
| `ha_services_list` | Available services by domain | Medium |
| `ha_state` | Single entity state + attributes | Low |
| `ha_states` | Batch entity states | Medium |
| `ha_states_by_domain` | All entities in a domain | Medium |
| `ha_history` | State change history | High |
| `ha_logbook` | Human-readable event log | Medium |
| `ha_statistics` | Pre-aggregated recorder stats | Medium |
| `ha_statistics_list` | Available statistic IDs | Low |
| `ha_calendar_events` | Calendar events in range | Medium |
| `ha_automations` | All automations with state | Medium |
| `ha_automation_get` | Full automation YAML config | Medium |
| `ha_template` | Jinja2 server-side rendering | Varies |
| `ha_camera_snapshot` | Camera proxy URL | Low |

### Write (11 tools — require `HA_WRITE_ENABLED=true`)

| Tool | Description |
|------|-------------|
| `ha_call_service` | Generic service call with target |
| `ha_light` | Light on/off/toggle, brightness, colour, temperature |
| `ha_climate` | HVAC mode, temperature, fan, preset |
| `ha_scene` | Activate scene |
| `ha_automation_trigger` | Manually trigger automation |
| `ha_automation_toggle` | Enable/disable automation |
| `ha_automation_create` | Create automation from config |
| `ha_script_run` | Run script with variables |
| `ha_webhook` | Fire HA webhook |
| `ha_notify` | Send notification |
| `ha_events` | Poll recent events (read) |

### Confirm-Gated (3 tools — require write + `confirm=true`)

| Tool | Description | Why |
|------|-------------|-----|
| `ha_lock` | Lock/unlock doors | Physical security |
| `ha_alarm` | Arm/disarm alarm panels | Physical security |
| `ha_automation_delete` | Delete automation | Irreversible |

## Output Format

All output is pipe-delimited for token efficiency:

```
# Entity state
light.living_room | on | brightness=178 | color_temp=350 | name=Living Room Light

# Sensor with unit
sensor.outdoor_temp | 18.3 °C | device_class=temperature | name=Outdoor Temp

# Area list
living_room | Living Room | floor_id=ground
kitchen | Kitchen | floor_id=ground

# History
## sensor.outdoor_temp
10:00 | 12.1
11:00 | 13.5
12:00 | 15.2

# Automation list
automation.night_lights | on | Night Lights | last=2026-04-03T22:00 | mode=single
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Write gate | `HA_WRITE_ENABLED=true` env var for any mutation |
| Confirm gate | `confirm=true` parameter for locks, alarms, deletions |
| Credential scrubbing | Bearer tokens and URLs stripped from all error output |
| Bearer auth | Optional `HA_MCP_API_TOKEN` for HTTP transport (timing-safe comparison) |
| Camera safety | Returns proxy URL, never raw image bytes |
| No caching | Credentials read from env at startup, never persisted |

## Multi-Instance Support

Target a specific instance with the `instance` parameter on any tool:

```
ha_states_by_domain domain="climate" instance="sandybay"
ha_states_by_domain domain="climate" instance="paddington"
```

Omit `instance` to query all configured instances — results are grouped by site.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `HA_URL` | HA base URL (single-instance) | Yes* |
| `HA_TOKEN` | Long-lived access token | Yes* |
| `HA_PROVIDERS` | Comma-separated provider names | No |
| `HA_{NAME}_URL` | Per-provider URL | Per-provider |
| `HA_{NAME}_TOKEN` | Per-provider token | Per-provider |
| `HA_WRITE_ENABLED` | Enable write operations | No (default: false) |
| `HA_MCP_TRANSPORT` | `stdio` or `http` | No (default: stdio) |
| `HA_MCP_HOST` | HTTP bind address | No (default: 127.0.0.1) |
| `HA_MCP_PORT` | HTTP port | No (default: 8766) |
| `HA_MCP_API_TOKEN` | Bearer token for HTTP transport | No |

\* Required if `HA_PROVIDERS` is not set.

## Development

```bash
# Install with dev deps
make install-dev

# Run tests
make test

# Coverage report
make test-cov

# Lint + format + type check
make check

# Run the server
make run
```

## Architecture

```
src/ha_blade_mcp/
├── server.py        — FastMCP 2.0 server, 36 tool definitions
├── client.py        — HAClient: httpx (REST) + websockets (WS), multi-provider
├── formatters.py    — Token-efficient pipe-delimited output
├── models.py        — ProviderConfig, write gate, confirm gate, credential scrubbing
├── auth.py          — Bearer token middleware for HTTP transport
└── __main__.py      — Entry point
```

**Dependencies:** `fastmcp`, `httpx`, `websockets`, `pydantic`. No `homeassistant` package dependency — pure HTTP/WS against the HA API.

## Sidereal Marketplace

This MCP conforms to the `home-v1` service contract (14/14 operations):
- **Required (4/4):** entity_list, entity_state, entity_history, area_list
- **Recommended (5/5):** scene_activate, climate_set, light_control, automation_list, automation_trigger
- **Optional (2/2):** camera_snapshot, energy_stats
- **Gated (3/3):** lock_control, alarm_control, automation_create

See `sidereal-plugin.yaml` for the full plugin manifest.

## License

MIT
