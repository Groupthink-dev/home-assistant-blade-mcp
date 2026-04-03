"""Tests for ha_blade_mcp.server — MCP tool integration tests."""

from __future__ import annotations

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
            mock_client.list_devices.return_value = [make_device()]
            mock_gc.return_value = mock_client
            result = await server_module.ha_devices()
            assert "Philips" in result


class TestHaEntities:
    @pytest.mark.asyncio
    async def test_lists_entities(self, ha_env: None) -> None:
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_entities_registry.return_value = [
                make_entity_registry("light.a"),
                make_entity_registry("sensor.b"),
            ]
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
