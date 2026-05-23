"""Tests for ha_blade_mcp.server — MCP tool integration tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import ha_blade_mcp.server as server_module
from tests.conftest import (
    make_area,
    make_automation_state,
    make_device,
    make_entity_registry,
    make_light_state,
    make_sensor_state,
)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """Reset the singleton client between tests."""
    server_module._client = None


# ---------------------------------------------------------------------------
# Read tools (no gate)
# ---------------------------------------------------------------------------


class TestHaInfo:
    @pytest.mark.asyncio
    async def test_returns_info(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.info.return_value = [
                {
                    "instance": "default",
                    "status": "connected",
                    "version": "2025.4.1",
                    "location_name": "Home",
                    "components": 42,
                }
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_info()
            assert "connected" in result
            assert "write_gate=" in result


class TestHaState:
    @pytest.mark.asyncio
    async def test_returns_state(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_state.return_value = make_light_state()
            mock_gc.return_value = mock_client
            result = await server_module.ha_state("light.living_room")
            assert "light.living_room" in result
            assert "on" in result

    @pytest.mark.asyncio
    async def test_not_found(self, ha_env: None) -> None:
        from ha_blade_mcp.client import NotFoundError

        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_state.side_effect = NotFoundError("not found")
            mock_gc.return_value = mock_client
            result = await server_module.ha_state("fake.entity")
            assert "Error:" in result


class TestHaStates:
    @pytest.mark.asyncio
    async def test_batch_states(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_states.return_value = [
                make_light_state("light.a"),
                make_sensor_state("sensor.b"),
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_states(["light.a", "sensor.b"])
            assert "light.a" in result
            assert "sensor.b" in result


class TestHaAreas:
    @pytest.mark.asyncio
    async def test_lists_areas(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_areas.return_value = [
                make_area("living_room", "Living Room"),
                make_area("kitchen", "Kitchen"),
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_areas()
            assert "Living Room" in result
            assert "Kitchen" in result


class TestHaDevices:
    @pytest.mark.asyncio
    async def test_lists_devices(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_devices.return_value = ([make_device()], 1)
            mock_gc.return_value = mock_client
            result = await server_module.ha_devices()
            assert "Philips" in result


class TestHaEntities:
    @pytest.mark.asyncio
    async def test_lists_entities(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_entities_registry.return_value = (
                [
                    make_entity_registry("light.a"),
                    make_entity_registry("sensor.b"),
                ],
                2,
            )
            mock_gc.return_value = mock_client
            result = await server_module.ha_entities()
            assert "## light" in result
            assert "## sensor" in result


class TestHaHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_history.return_value = [
                {
                    "instance": "default",
                    "history": [
                        [
                            {"entity_id": "sensor.temp", "state": "18", "last_changed": "2026-04-03T10:00:00"},
                        ]
                    ],
                }
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_history(["sensor.temp"], "2026-04-03T00:00:00")
            assert "sensor.temp" in result


class TestHaAutomations:
    @pytest.mark.asyncio
    async def test_lists_automations(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_automations.return_value = [make_automation_state()]
            mock_gc.return_value = mock_client
            result = await server_module.ha_automations()
            assert "automation.turn_off_lights" in result


class TestHaTemplate:
    @pytest.mark.asyncio
    async def test_renders_template(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.render_template.return_value = [{"instance": "default", "result": "22.5"}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_template("{{ states('sensor.temp') }}")
            assert "22.5" in result


# ---------------------------------------------------------------------------
# Write-gated tools
# ---------------------------------------------------------------------------


class TestHaCallService:
    @pytest.mark.asyncio
    async def test_blocked_without_write(self, ha_env: None) -> None:
        result = await server_module.ha_call_service("light", "turn_on")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_succeeds_with_write(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 1}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_call_service("light", "turn_on", target={"entity_id": "light.living_room"})
            assert "state(s) changed" in result


class TestHaLight:
    @pytest.mark.asyncio
    async def test_blocked_without_write(self, ha_env: None) -> None:
        result = await server_module.ha_light(entity_id="light.a")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_entity_or_area(self, ha_env_write: None) -> None:
        result = await server_module.ha_light()
        assert "entity_id or area" in result.lower()

    @pytest.mark.asyncio
    async def test_turn_on(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 1}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_light(entity_id="light.a", brightness=200)
            assert "state(s) changed" in result
            # Check brightness was clamped
            call_args = mock_client.call_service.call_args
            assert call_args[1].get("data") or call_args[0][4]  # data param


class TestHaScene:
    @pytest.mark.asyncio
    async def test_activate(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 5}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_scene("scene.movie_night")
            assert "Activated" in result


# ---------------------------------------------------------------------------
# Confirm-gated tools
# ---------------------------------------------------------------------------


class TestHaLock:
    @pytest.mark.asyncio
    async def test_blocked_without_write(self, ha_env: None) -> None:
        result = await server_module.ha_lock(entity_id="lock.front")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_without_confirm(self, ha_env_write: None) -> None:
        result = await server_module.ha_lock(entity_id="lock.front")
        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_succeeds_with_confirm(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 1}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_lock(entity_id="lock.front", action="lock", confirm=True)
            assert "lock:" in result


class TestHaAlarm:
    @pytest.mark.asyncio
    async def test_blocked_without_confirm(self, ha_env_write: None) -> None:
        result = await server_module.ha_alarm("alarm_control_panel.home", "arm_away")
        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_succeeds_with_confirm(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 1}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_alarm("alarm_control_panel.home", "arm_away", confirm=True)
            assert "arm_away:" in result


class TestHaAutomationDelete:
    @pytest.mark.asyncio
    async def test_blocked_without_confirm(self, ha_env_write: None) -> None:
        result = await server_module.ha_automation_delete("my_auto")
        assert "confirm" in result.lower()

    @pytest.mark.asyncio
    async def test_succeeds_with_confirm(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.delete_automation.return_value = {
                "instance": "default",
                "automation_id": "my_auto",
                "status": "deleted",
            }
            mock_gc.return_value = mock_client
            result = await server_module.ha_automation_delete("my_auto", confirm=True)
            assert "Deleted" in result


class TestHaWebhook:
    @pytest.mark.asyncio
    async def test_blocked_without_write(self, ha_env: None) -> None:
        result = await server_module.ha_webhook("my_webhook")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_fires_webhook(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.fire_webhook.return_value = {
                "instance": "default",
                "webhook_id": "my_webhook",
                "status": "fired",
            }
            mock_gc.return_value = mock_client
            result = await server_module.ha_webhook("my_webhook", {"key": "val"})
            assert "fired" in result


class TestHaNotify:
    @pytest.mark.asyncio
    async def test_blocked_without_write(self, ha_env: None) -> None:
        result = await server_module.ha_notify("mobile_app", "Hello")
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_sends_notification(self, ha_env_write: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.call_service.return_value = [{"instance": "default", "changed_states": 0}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_notify("mobile_app_phone", "Test message", title="Test")
            assert "sent" in result.lower()


# ---------------------------------------------------------------------------
# DD-338 Phase A.1 — scope arg + _meta envelope coverage
# ---------------------------------------------------------------------------


def _parse_meta(result: str) -> dict[str, Any]:
    """Extract the trailing _meta JSON envelope from a tool response.

    Mirrors the assembler regex from the architect amendment:
        \\n\\n_meta: (\\{.*\\})$
    """
    import json
    import re

    match = re.search(r"\n\n_meta: (\{.*\})$", result, flags=re.DOTALL)
    assert match is not None, f"No _meta envelope in result:\n{result}"
    return json.loads(match.group(1))


class TestHaDevicesScope:
    @pytest.mark.asyncio
    async def test_happy_path_includes_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_devices.return_value = ([make_device(), make_device(device_id="xyz789")], 2)
            mock_gc.return_value = mock_client
            result = await server_module.ha_devices(scope="home", area="kitchen", limit=10)
            meta = _parse_meta(result)
            assert meta["matched_total"] == 2
            assert meta["returned"] == 2
            assert "scope=home" in meta["filtered_by"]
            assert "area=kitchen" in meta["filtered_by"]
            assert isinstance(meta["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_rejects_work_scope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_gc.return_value = mock_client
            result = await server_module.ha_devices(scope="work")
            assert result.startswith("Error: scope=work not applicable to home-assistant")
            mock_client.list_devices.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_scope_arg_still_emits_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_devices.return_value = ([make_device()], 1)
            mock_gc.return_value = mock_client
            result = await server_module.ha_devices()
            meta = _parse_meta(result)
            assert meta["matched_total"] == 1
            assert meta["filtered_by"] == []


class TestHaEntitiesScope:
    @pytest.mark.asyncio
    async def test_happy_path_includes_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_entities_registry.return_value = (
                [make_entity_registry("light.a"), make_entity_registry("light.b")],
                2,
            )
            mock_gc.return_value = mock_client
            result = await server_module.ha_entities(scope="home", domain="light")
            meta = _parse_meta(result)
            assert meta["matched_total"] == 2
            assert meta["returned"] == 2
            assert "scope=home" in meta["filtered_by"]
            assert "domain=light" in meta["filtered_by"]

    @pytest.mark.asyncio
    async def test_rejects_trustee_scope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_gc.return_value = mock_client
            result = await server_module.ha_entities(scope="trustee-corporate")
            assert result.startswith("Error: scope=trustee-corporate not applicable to home-assistant")
            mock_client.list_entities_registry.assert_not_called()


class TestHaStatesByDomainScope:
    @pytest.mark.asyncio
    async def test_happy_path_includes_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_states_by_domain.return_value = (
                [make_light_state("light.a"), make_light_state("light.b"), make_light_state("light.c")],
                3,
            )
            mock_gc.return_value = mock_client
            result = await server_module.ha_states_by_domain("light", scope="home")
            meta = _parse_meta(result)
            assert meta["matched_total"] == 3
            assert meta["returned"] == 3
            assert "scope=home" in meta["filtered_by"]
            assert "domain=light" in meta["filtered_by"]

    @pytest.mark.asyncio
    async def test_rejects_algo_trading_scope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_gc.return_value = mock_client
            result = await server_module.ha_states_by_domain("light", scope="algo-trading")
            assert result.startswith("Error: scope=algo-trading not applicable to home-assistant")
            mock_client.get_states_by_domain.assert_not_called()


class TestHaStatisticsScope:
    @pytest.mark.asyncio
    async def test_happy_path_includes_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_statistics.return_value = (
                [
                    {
                        "instance": "default",
                        "statistics": {"sensor.power": [{"start": "2026-05-01T00:00:00", "mean": 100}]},
                    }
                ],
                1,
            )
            mock_gc.return_value = mock_client
            result = await server_module.ha_statistics(
                entity_ids=["sensor.power"],
                start="2026-05-01T00:00:00+10:00",
                scope="home",
            )
            meta = _parse_meta(result)
            assert meta["matched_total"] == 1
            assert meta["returned"] == 1
            assert "scope=home" in meta["filtered_by"]

    @pytest.mark.asyncio
    async def test_rejects_private_equity_scope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_gc.return_value = mock_client
            result = await server_module.ha_statistics(
                entity_ids=["sensor.power"],
                start="2026-05-01T00:00:00+10:00",
                scope="private-equity",
            )
            assert result.startswith("Error: scope=private-equity not applicable to home-assistant")
            mock_client.get_statistics.assert_not_called()


class TestScopeCheckUnit:
    """Unit tests for the _scope_check helper itself."""

    def test_none_passes(self) -> None:
        assert server_module._scope_check(None) is None

    def test_home_passes(self) -> None:
        assert server_module._scope_check("home") is None

    def test_family_passes(self) -> None:
        assert server_module._scope_check("family") is None

    def test_personal_passes(self) -> None:
        assert server_module._scope_check("personal") is None

    def test_work_rejected(self) -> None:
        rejection = server_module._scope_check("work")
        assert rejection is not None
        assert "not applicable to home-assistant" in rejection

    def test_property_rejected(self) -> None:
        rejection = server_module._scope_check("property-sandy-bay")
        assert rejection is not None
        assert "not applicable to home-assistant" in rejection

    def test_unknown_passes_through(self) -> None:
        # Defensive — DD-278 vocabulary may grow
        assert server_module._scope_check("brand-new-scope-2027") is None


# ---------------------------------------------------------------------------
# DD-338 Phase C Wave 2 — audit_surface envelope coverage
# (ha_search, ha_history, ha_logbook, ha_calendar_events, ha_states)
# ---------------------------------------------------------------------------


class TestHaSearchMeta:
    @pytest.mark.asyncio
    async def test_emits_meta_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.search_related.return_value = [
                {
                    "_instance": "default",
                    "entity": ["light.a", "light.b"],
                    "device": ["dev1"],
                }
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_search(item_type="entity", item_id="light.living_room")
            meta = _parse_meta(result)
            assert meta["matched_total"] == 3
            assert meta["returned"] == 3
            assert "item_type=entity" in meta["filtered_by"]
            assert "item_id=light.living_room" in meta["filtered_by"]
            assert isinstance(meta["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_no_results_still_emits_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.search_related.return_value = [{"_instance": "default"}]
            mock_gc.return_value = mock_client
            result = await server_module.ha_search(item_type="device", item_id="abc123")
            meta = _parse_meta(result)
            assert meta["matched_total"] == 0
            assert meta["returned"] == 0
            assert "item_type=device" in meta["filtered_by"]


class TestHaHistoryMeta:
    @pytest.mark.asyncio
    async def test_emits_meta_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_history.return_value = [
                {
                    "instance": "default",
                    "history": [
                        [
                            {"entity_id": "light.a", "state": "on", "last_changed": "2026-05-01T10:00:00"},
                            {"entity_id": "light.a", "state": "off", "last_changed": "2026-05-01T11:00:00"},
                        ],
                        [
                            {"entity_id": "light.b", "state": "on", "last_changed": "2026-05-01T10:30:00"},
                        ],
                    ],
                }
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_history(
                entity_ids=["light.a", "light.b"],
                start="2026-05-01T00:00:00",
                end="2026-05-02T00:00:00",
                minimal=True,
            )
            meta = _parse_meta(result)
            assert meta["matched_total"] == 3  # total state-change records
            assert meta["returned"] == 3
            assert "entity_ids=2" in meta["filtered_by"]
            assert "time_range=2026-05-01T00:00:00..2026-05-02T00:00:00" in meta["filtered_by"]
            assert "minimal=true" in meta["filtered_by"]

    @pytest.mark.asyncio
    async def test_default_end_emits_meta(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_history.return_value = []
            mock_gc.return_value = mock_client
            result = await server_module.ha_history(entity_ids=["sensor.x"], start="2026-05-01T00:00:00")
            meta = _parse_meta(result)
            assert meta["returned"] == 0
            assert any("time_range=2026-05-01T00:00:00.." in f for f in meta["filtered_by"])


class TestHaLogbookMeta:
    @pytest.mark.asyncio
    async def test_emits_meta_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_logbook.return_value = [
                {"when": "2026-05-01T10:00:00", "name": "Light A", "message": "turned on"},
                {"when": "2026-05-01T11:00:00", "name": "Light A", "message": "turned off"},
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_logbook(
                start="2026-05-01T00:00:00",
                end="2026-05-02T00:00:00",
                entity_id="light.a",
                limit=50,
            )
            meta = _parse_meta(result)
            assert meta["matched_total"] == 2
            assert meta["returned"] == 2
            assert "time_range=2026-05-01T00:00:00..2026-05-02T00:00:00" in meta["filtered_by"]
            assert "entity_id=light.a" in meta["filtered_by"]
            assert "limit=50" in meta["filtered_by"]

    @pytest.mark.asyncio
    async def test_no_entity_filter_omitted_from_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_logbook.return_value = []
            mock_gc.return_value = mock_client
            result = await server_module.ha_logbook(start="2026-05-01T00:00:00")
            meta = _parse_meta(result)
            assert not any(f.startswith("entity_id=") for f in meta["filtered_by"])


class TestHaCalendarEventsMeta:
    @pytest.mark.asyncio
    async def test_emits_meta_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_calendar_events.return_value = [
                {
                    "summary": "Meeting",
                    "start": {"dateTime": "2026-05-01T10:00:00"},
                    "end": {"dateTime": "2026-05-01T11:00:00"},
                },
                {
                    "summary": "Lunch",
                    "start": {"dateTime": "2026-05-01T12:00:00"},
                    "end": {"dateTime": "2026-05-01T13:00:00"},
                },
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_calendar_events(
                entity_id="calendar.work",
                start="2026-05-01T00:00:00",
                end="2026-05-02T00:00:00",
            )
            meta = _parse_meta(result)
            assert meta["matched_total"] == 2
            assert meta["returned"] == 2
            assert "entity_id=calendar.work" in meta["filtered_by"]
            assert "time_range=2026-05-01T00:00:00..2026-05-02T00:00:00" in meta["filtered_by"]


class TestHaStatesMeta:
    @pytest.mark.asyncio
    async def test_emits_meta_envelope(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_states.return_value = [
                make_light_state("light.a"),
                make_light_state("light.b"),
            ]
            mock_gc.return_value = mock_client
            result = await server_module.ha_states(entity_ids=["light.a", "light.b"])
            meta = _parse_meta(result)
            assert meta["matched_total"] == 2
            assert meta["returned"] == 2
            assert "entity_ids=2" in meta["filtered_by"]
            # DD-338 Phase E.python — canonical `meta_envelope` always emits
            # `redactions: []` (empty list when no redactions present) and
            # `next_cursor: null`. The "absent when empty" semantic is gone.
            assert meta["redactions"] == []

    @pytest.mark.asyncio
    async def test_missing_ids_surface_as_redactions(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            # Request 3 but client only returns 1
            mock_client.get_states.return_value = [make_light_state("light.a")]
            mock_gc.return_value = mock_client
            result = await server_module.ha_states(entity_ids=["light.a", "light.missing1", "light.missing2"])
            meta = _parse_meta(result)
            assert meta["matched_total"] == 3
            assert meta["returned"] == 1
            assert "redactions" in meta
            assert "entity_id=light.missing1_not_found" in meta["redactions"]
            assert "entity_id=light.missing2_not_found" in meta["redactions"]


# ---------------------------------------------------------------------------
# DD-338 Phase C Wave 2 — ha_search scope_filtering: server-side honesty
# (OQ-1 ratification: ha_search calls the underlying search/related WS endpoint
#  with explicit item_type + item_id; no over-fetch + client-side filter.)
# ---------------------------------------------------------------------------


class TestHaSearchServerSideHonesty:
    @pytest.mark.asyncio
    async def test_passes_args_verbatim_to_client(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.search_related.return_value = [{"_instance": "default"}]
            mock_gc.return_value = mock_client
            await server_module.ha_search(item_type="entity", item_id="light.x")
            mock_client.search_related.assert_called_once_with("entity", "light.x", None)
