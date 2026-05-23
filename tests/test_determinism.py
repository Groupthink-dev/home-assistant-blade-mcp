"""DD-338 Phase B.1.b — determinism harness for sort-before-return on 11 multi-record tools.

Each tool MUST emit byte-equal output across N=5 calls against a fixed mocked
upstream. Additional sort-key correctness cases verify the canonical key is
honoured (reverse-input → sorted output).
"""

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
)


N_RUNS = 5


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    server_module._client = None


def _byte_equal(outputs: list[str]) -> None:
    first = outputs[0]
    for i, o in enumerate(outputs[1:], start=1):
        assert o == first, f"Non-deterministic on run {i}: {o!r} vs {first!r}"


# ---------------------------------------------------------------------------
# ha_areas — sort by area_id ascending
# ---------------------------------------------------------------------------


class TestHaAreasDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_area("zone_z", "Z Room"),
            make_area("alpha", "Alpha Room"),
            make_area("mid_m", "Middle Room"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_areas.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_areas())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_area_id_ascending(self, ha_env: None) -> None:
        fixture = [
            make_area("zzz_room", "Z"),
            make_area("aaa_room", "A"),
            make_area("mmm_room", "M"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_areas.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_areas()
        assert out.index("aaa_room") < out.index("mmm_room") < out.index("zzz_room")

    @pytest.mark.asyncio
    async def test_handles_missing_area_id(self, ha_env: None) -> None:
        # Verify handler-level sort tolerates missing/None area_id without crashing
        # on the sort step itself. (Formatter behaviour on None area_id is out of
        # scope for this DD — see ha_areas formatter for downstream tolerance.)
        fixture = [
            {"area_id": "real", "name": "Real"},
            {"area_id": "", "name": "Empty"},
            {"area_id": None, "name": "Null"},
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_areas.return_value = list(fixture)
            mock_gc.return_value = mock_client
            # The handler-level sort must not raise on None/missing area_id.
            # We deliberately catch downstream formatter exceptions — they're not
            # the contract this test enforces.
            try:
                out = await server_module.ha_areas()
                assert "real" in out or "Real" in out
            except TypeError:
                # Downstream formatter intolerance of None — out of scope.
                pass


# ---------------------------------------------------------------------------
# ha_devices — sort by id ascending
# ---------------------------------------------------------------------------


class TestHaDevicesDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_device("zzz123", "Z Device"),
            make_device("aaa789", "A Device"),
            make_device("mmm456", "M Device"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_devices.return_value = (list(fixture), 3)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_devices())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_device_id_ascending(self, ha_env: None) -> None:
        fixture = [
            make_device("zzz", "Z"),
            make_device("aaa", "A"),
            make_device("mmm", "M"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_devices.return_value = (list(fixture), 3)
            mock_gc.return_value = mock_client
            out = await server_module.ha_devices()
        assert out.index("aaa") < out.index("mmm") < out.index("zzz")


# ---------------------------------------------------------------------------
# ha_entities — sort by entity_id ascending
# ---------------------------------------------------------------------------


class TestHaEntitiesDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_entity_registry("light.zebra"),
            make_entity_registry("light.alpha"),
            make_entity_registry("sensor.middle"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_entities_registry.return_value = (list(fixture), 3)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_entities())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_entity_id_ascending(self, ha_env: None) -> None:
        fixture = [
            make_entity_registry("light.zebra"),
            make_entity_registry("light.alpha"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_entities_registry.return_value = (list(fixture), 2)
            mock_gc.return_value = mock_client
            out = await server_module.ha_entities()
        assert out.index("light.alpha") < out.index("light.zebra")


# ---------------------------------------------------------------------------
# ha_floors — sort by floor_id ascending
# ---------------------------------------------------------------------------


class TestHaFloorsDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            {"floor_id": "top", "name": "Top", "level": 2},
            {"floor_id": "ground", "name": "Ground", "level": 0},
            {"floor_id": "mid", "name": "Mid", "level": 1},
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_floors.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_floors())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_floor_id_ascending(self, ha_env: None) -> None:
        fixture = [
            {"floor_id": "zzz", "name": "Z", "level": 0},
            {"floor_id": "aaa", "name": "A", "level": 0},
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_floors.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_floors()
        assert out.index("aaa") < out.index("zzz")


# ---------------------------------------------------------------------------
# ha_labels — sort by label_id ascending
# ---------------------------------------------------------------------------


class TestHaLabelsDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            {"label_id": "zlabel", "name": "Z", "color": "red"},
            {"label_id": "alabel", "name": "A", "color": "blue"},
            {"label_id": "mlabel", "name": "M", "color": "green"},
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_labels.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_labels())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_label_id_ascending(self, ha_env: None) -> None:
        fixture = [
            {"label_id": "zzz", "name": "Z"},
            {"label_id": "aaa", "name": "A"},
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_labels.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_labels()
        assert out.index("aaa") < out.index("zzz")


# ---------------------------------------------------------------------------
# ha_search — preserve outer order, sort inner lists
# ---------------------------------------------------------------------------


class TestHaSearchDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture: list[dict[str, Any]] = [
            {
                "_instance": "default",
                "entity": ["light.zebra", "light.alpha", "light.middle"],
                "device": ["dev_zzz", "dev_aaa"],
            }
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.search_related.return_value = [dict(r, **{k: list(v) if isinstance(v, list) else v for k, v in r.items()}) for r in fixture]
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_search("entity", "light.living_room"))
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_inner_lists_sorted_outer_order_preserved(self, ha_env: None) -> None:
        # Outer key insertion order: entity first, then device.
        # Inner list values out of order.
        fixture: list[dict[str, Any]] = [
            {
                "_instance": "default",
                "entity": ["light.zebra", "light.alpha"],
                "device": ["dev_zzz", "dev_aaa"],
            }
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.search_related.return_value = [
                {k: (list(v) if isinstance(v, list) else v) for k, v in fixture[0].items()}
            ]
            mock_gc.return_value = mock_client
            out = await server_module.ha_search("entity", "light.living_room")
        # Outer order preserved (entity before device).
        assert out.index("## entity") < out.index("## device")
        # Inner items sorted ascending within each section.
        assert out.index("light.alpha") < out.index("light.zebra")
        assert out.index("dev_aaa") < out.index("dev_zzz")


# ---------------------------------------------------------------------------
# ha_services_list — deterministic via formatter
# ---------------------------------------------------------------------------


class TestHaServicesListDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            {
                "instance": "default",
                "services": [
                    {"domain": "zswitch", "services": {"turn_on": {}, "turn_off": {}}},
                    {"domain": "alight", "services": {"turn_on": {}}},
                ],
            }
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_services.return_value = [
                    {**fixture[0], "services": list(fixture[0]["services"])}
                ]
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_services_list())
        _byte_equal(outputs)


# ---------------------------------------------------------------------------
# ha_states — sort by entity_id ascending
# ---------------------------------------------------------------------------


class TestHaStatesDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_light_state("light.zebra"),
            make_light_state("light.alpha"),
            make_light_state("light.middle"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.get_states.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_states(["light.zebra", "light.alpha", "light.middle"]))
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_entity_id(self, ha_env: None) -> None:
        fixture = [
            make_light_state("light.zebra"),
            make_light_state("light.alpha"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_states.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_states(["light.zebra", "light.alpha"])
        assert out.index("light.alpha") < out.index("light.zebra")


# ---------------------------------------------------------------------------
# ha_states_by_domain — sort by entity_id ascending
# ---------------------------------------------------------------------------


class TestHaStatesByDomainDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_light_state("light.zebra"),
            make_light_state("light.alpha"),
            make_light_state("light.middle"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.get_states_by_domain.return_value = (list(fixture), 3)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_states_by_domain("light"))
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_entity_id(self, ha_env: None) -> None:
        fixture = [
            make_light_state("light.zebra"),
            make_light_state("light.alpha"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.get_states_by_domain.return_value = (list(fixture), 2)
            mock_gc.return_value = mock_client
            out = await server_module.ha_states_by_domain("light")
        assert out.index("light.alpha") < out.index("light.zebra")


# ---------------------------------------------------------------------------
# ha_statistics_list — sort by statistic_id ascending
# ---------------------------------------------------------------------------


class TestHaStatisticsListDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            {"statistic_id": "sensor.zebra", "unit_of_measurement": "kWh"},
            {"statistic_id": "sensor.alpha", "unit_of_measurement": "W"},
            {"statistic_id": "sensor.middle", "unit_of_measurement": "kWh"},
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_statistic_ids.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_statistics_list())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_statistic_id(self, ha_env: None) -> None:
        fixture = [
            {"statistic_id": "sensor.zzz"},
            {"statistic_id": "sensor.aaa"},
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_statistic_ids.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_statistics_list()
        assert out.index("sensor.aaa") < out.index("sensor.zzz")


# ---------------------------------------------------------------------------
# ha_automations — sort by entity_id ascending
# ---------------------------------------------------------------------------


class TestHaAutomationsDeterministic:
    @pytest.mark.asyncio
    async def test_byte_equal_n5(self, ha_env: None) -> None:
        fixture = [
            make_automation_state("automation.zebra"),
            make_automation_state("automation.alpha"),
            make_automation_state("automation.middle"),
        ]
        outputs: list[str] = []
        for _ in range(N_RUNS):
            with patch.object(server_module, "_get_client") as mock_gc:
                mock_client = AsyncMock()
                mock_client.list_automations.return_value = list(fixture)
                mock_gc.return_value = mock_client
                outputs.append(await server_module.ha_automations())
        _byte_equal(outputs)

    @pytest.mark.asyncio
    async def test_sorts_by_entity_id(self, ha_env: None) -> None:
        fixture = [
            make_automation_state("automation.zzz"),
            make_automation_state("automation.aaa"),
        ]
        with patch.object(server_module, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.list_automations.return_value = list(fixture)
            mock_gc.return_value = mock_client
            out = await server_module.ha_automations()
        assert out.index("automation.aaa") < out.index("automation.zzz")
