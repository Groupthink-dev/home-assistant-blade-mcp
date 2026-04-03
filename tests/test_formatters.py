"""Tests for ha_blade_mcp.formatters — token-efficient output."""

from __future__ import annotations

from ha_blade_mcp.formatters import (
    format_areas,
    format_automations,
    format_calendar_events,
    format_config,
    format_devices,
    format_entity_list,
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
    format_statistic_ids,
    format_statistics,
    format_template_result,
)
from tests.conftest import (
    make_area,
    make_automation_state,
    make_device,
    make_entity_registry,
    make_entity_state,
    make_light_state,
    make_sensor_state,
)


class TestFormatInfo:
    def test_single_instance(self) -> None:
        result = format_info(
            [
                {
                    "instance": "default",
                    "status": "connected",
                    "version": "2025.4.1",
                    "location_name": "Home",
                    "components": 42,
                }
            ]
        )
        assert "default" in result
        assert "connected" in result
        assert "v2025.4.1" in result
        assert "components=42" in result

    def test_empty(self) -> None:
        assert "no instances" in format_info([])


class TestFormatEntityState:
    def test_light(self) -> None:
        entity = make_light_state()
        result = format_entity_state(entity)
        assert "light.living_room" in result
        assert "on" in result
        assert "brightness=178" in result
        assert "color_temp=350" in result

    def test_sensor_with_unit(self) -> None:
        entity = make_sensor_state()
        result = format_entity_state(entity)
        assert "sensor.outdoor_temp" in result
        assert "18.3 °C" in result

    def test_field_selection(self) -> None:
        entity = make_light_state()
        result = format_entity_state(entity, fields=["brightness"])
        assert "brightness=178" in result
        assert "color_temp" not in result

    def test_binary_sensor(self) -> None:
        entity = make_entity_state(
            "binary_sensor.front_door",
            "off",
            {"device_class": "door", "friendly_name": "Front Door"},
        )
        result = format_entity_state(entity)
        assert "device_class=door" in result


class TestFormatEntityList:
    def test_grouped_by_domain(self) -> None:
        entities = [
            make_light_state("light.kitchen"),
            make_sensor_state("sensor.temp"),
            make_light_state("light.bedroom"),
        ]
        result = format_entity_list(entities)
        assert "## light (2)" in result
        assert "## sensor (1)" in result

    def test_empty(self) -> None:
        assert "no entities" in format_entity_list([])


class TestFormatAreas:
    def test_basic(self) -> None:
        areas = [
            make_area("living_room", "Living Room", "ground"),
            make_area("kitchen", "Kitchen", "ground"),
        ]
        result = format_areas(areas)
        assert "living_room" in result
        assert "Kitchen" in result
        assert "ground" in result

    def test_empty(self) -> None:
        assert "no areas" in format_areas([])


class TestFormatDevices:
    def test_basic(self) -> None:
        devices = [make_device()]
        result = format_devices(devices)
        assert "abc123" in result
        assert "Philips" in result
        assert "Hue White" in result

    def test_empty(self) -> None:
        assert "no devices" in format_devices([])


class TestFormatEntityRegistry:
    def test_grouped_by_domain(self) -> None:
        entities = [
            make_entity_registry("light.a", area_id="living"),
            make_entity_registry("sensor.b", area_id="kitchen"),
        ]
        result = format_entity_registry(entities)
        assert "## light (1)" in result
        assert "## sensor (1)" in result

    def test_shows_labels(self) -> None:
        entity = make_entity_registry("light.a", labels=["security"])
        result = format_entity_registry([entity])
        assert "labels=security" in result


class TestFormatAutomations:
    def test_basic(self) -> None:
        auto = make_automation_state()
        result = format_automations([auto])
        assert "automation.turn_off_lights" in result
        assert "on" in result

    def test_empty(self) -> None:
        assert "no automations" in format_automations([])


class TestFormatHistory:
    def test_basic(self) -> None:
        result = format_history(
            [
                {
                    "instance": "default",
                    "history": [
                        [
                            {"entity_id": "sensor.temp", "state": "18", "last_changed": "2026-04-03T10:00:00"},
                            {"entity_id": "sensor.temp", "state": "19", "last_changed": "2026-04-03T11:00:00"},
                        ]
                    ],
                }
            ]
        )
        assert "sensor.temp" in result
        assert "10:00" in result
        assert "18" in result

    def test_empty(self) -> None:
        assert "no history" in format_history([])


class TestFormatLogbook:
    def test_basic(self) -> None:
        result = format_logbook(
            [
                {
                    "when": "2026-04-03T10:30:00+11:00",
                    "name": "Living Room Light",
                    "message": "turned on",
                    "entity_id": "light.living_room",
                }
            ]
        )
        assert "10:30" in result
        assert "Living Room Light" in result
        assert "turned on" in result

    def test_empty(self) -> None:
        assert "no logbook" in format_logbook([])


class TestFormatServices:
    def test_compact(self) -> None:
        from ha_blade_mcp.formatters import format_services

        result = format_services(
            [
                {
                    "instance": "default",
                    "services": [{"domain": "light", "services": {"turn_on": {}, "turn_off": {}, "toggle": {}}}],
                }
            ]
        )
        assert "light:" in result
        assert "turn_on" in result

    def test_empty(self) -> None:
        from ha_blade_mcp.formatters import format_services

        assert "no services" in format_services([])


class TestFormatCalendarEvents:
    def test_basic(self) -> None:
        result = format_calendar_events(
            [
                {
                    "start": {"dateTime": "2026-04-03T10:00:00"},
                    "end": {"dateTime": "2026-04-03T11:00:00"},
                    "summary": "Team Meeting",
                    "location": "Office",
                }
            ]
        )
        assert "10:00" in result
        assert "Team Meeting" in result
        assert "location=Office" in result

    def test_empty(self) -> None:
        assert "no events" in format_calendar_events([])


class TestFormatStatistics:
    def test_basic(self) -> None:
        result = format_statistics(
            [
                {
                    "instance": "default",
                    "statistics": {
                        "sensor.energy": [
                            {"start": "2026-04-03T10:00:00", "mean": 1.5, "min": 1.0, "max": 2.0},
                        ],
                    },
                }
            ]
        )
        assert "sensor.energy" in result
        assert "mean=1.5" in result

    def test_empty(self) -> None:
        assert "no statistics" in format_statistics([])


class TestFormatStatisticIds:
    def test_basic(self) -> None:
        result = format_statistic_ids(
            [
                {
                    "statistic_id": "sensor.energy",
                    "unit_of_measurement": "kWh",
                    "source": "recorder",
                    "name": "Energy Usage",
                }
            ]
        )
        assert "sensor.energy" in result
        assert "kWh" in result

    def test_empty(self) -> None:
        assert "no statistic" in format_statistic_ids([])


class TestFormatSearchRelated:
    def test_basic(self) -> None:
        result = format_search_related(
            [
                {
                    "_instance": "default",
                    "entity": ["light.a", "sensor.b"],
                    "device": ["dev_1"],
                }
            ]
        )
        assert "entity (2)" in result
        assert "device (1)" in result

    def test_empty(self) -> None:
        assert "no results" in format_search_related([])


class TestFormatServiceResult:
    def test_single(self) -> None:
        result = format_service_result([{"instance": "default", "changed_states": 3}])
        assert "3 state(s) changed" in result


class TestFormatTemplateResult:
    def test_single(self) -> None:
        result = format_template_result([{"instance": "default", "result": "22.5"}])
        assert "22.5" in result

    def test_multi(self) -> None:
        result = format_template_result(
            [
                {"instance": "sb", "result": "22.5"},
                {"instance": "pad", "result": "19.0"},
            ]
        )
        assert "### sb" in result
        assert "### pad" in result


class TestFormatConfig:
    def test_basic(self) -> None:
        result = format_config(
            [
                {
                    "instance": "default",
                    "version": "2025.4.1",
                    "location_name": "Home",
                    "time_zone": "Australia/Hobart",
                    "currency": "AUD",
                    "elevation": 50,
                    "unit_system": "°C",
                    "components_count": 42,
                }
            ]
        )
        assert "default" in result
        assert "2025.4.1" in result
        assert "Australia/Hobart" in result


class TestFormatErrorLog:
    def test_basic(self) -> None:
        result = format_error_log(
            [
                {
                    "instance": "default",
                    "lines": ["2026-04-03 ERROR some error occurred"],
                }
            ]
        )
        assert "some error occurred" in result

    def test_empty(self) -> None:
        result = format_error_log([{"instance": "default", "lines": []}])
        assert "no errors" in result


class TestFormatFloors:
    def test_basic(self) -> None:
        result = format_floors([{"floor_id": "ground", "name": "Ground Floor", "level": 0}])
        assert "ground" in result
        assert "Ground Floor" in result

    def test_empty(self) -> None:
        assert "no floors" in format_floors([])


class TestFormatLabels:
    def test_basic(self) -> None:
        result = format_labels([{"label_id": "security", "name": "Security", "color": "red"}])
        assert "security" in result
        assert "color=red" in result

    def test_empty(self) -> None:
        assert "no labels" in format_labels([])
