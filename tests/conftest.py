"""Shared fixtures and mock builders for Home Assistant Blade MCP tests."""

from __future__ import annotations

import os
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no real HA credentials leak into tests."""
    for key in list(os.environ.keys()):
        if key.startswith("HA_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def ha_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up single-provider HA environment."""
    monkeypatch.setenv("HA_URL", "http://ha.local:8123")
    monkeypatch.setenv("HA_TOKEN", "test-token-123")


@pytest.fixture()
def ha_env_multi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up multi-provider HA environment."""
    monkeypatch.setenv("HA_PROVIDERS", "sandybay,paddington")
    monkeypatch.setenv("HA_SANDYBAY_URL", "http://sb.local:8123")
    monkeypatch.setenv("HA_SANDYBAY_TOKEN", "sb-token")
    monkeypatch.setenv("HA_PADDINGTON_URL", "http://pad.local:8123")
    monkeypatch.setenv("HA_PADDINGTON_TOKEN", "pad-token")


@pytest.fixture()
def ha_env_write(monkeypatch: pytest.MonkeyPatch, ha_env: None) -> None:
    """Single-provider with write enabled."""
    monkeypatch.setenv("HA_WRITE_ENABLED", "true")


# ---------------------------------------------------------------------------
# Mock entity builders
# ---------------------------------------------------------------------------


def make_entity_state(
    entity_id: str = "light.living_room",
    state: str = "on",
    attributes: dict[str, Any] | None = None,
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock HA entity state dict."""
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {"friendly_name": entity_id.split(".")[1].replace("_", " ").title()},
        "last_changed": "2026-04-03T10:00:00+11:00",
        "last_updated": "2026-04-03T10:00:00+11:00",
        "_instance": instance,
    }


def make_light_state(
    entity_id: str = "light.living_room",
    state: str = "on",
    brightness: int = 178,
    color_temp: int = 350,
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock light entity state."""
    return make_entity_state(
        entity_id,
        state,
        {
            "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
            "brightness": brightness,
            "color_temp": color_temp,
            "supported_color_modes": ["color_temp", "xy"],
        },
        instance,
    )


def make_sensor_state(
    entity_id: str = "sensor.outdoor_temp",
    state: str = "18.3",
    unit: str = "°C",
    device_class: str = "temperature",
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock sensor entity state."""
    return make_entity_state(
        entity_id,
        state,
        {
            "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
            "unit_of_measurement": unit,
            "device_class": device_class,
        },
        instance,
    )


def make_automation_state(
    entity_id: str = "automation.turn_off_lights",
    state: str = "on",
    last_triggered: str = "2026-04-03T22:00:00+11:00",
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock automation entity state."""
    return make_entity_state(
        entity_id,
        state,
        {
            "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
            "last_triggered": last_triggered,
            "mode": "single",
        },
        instance,
    )


def make_area(
    area_id: str = "living_room",
    name: str = "Living Room",
    floor_id: str | None = "ground",
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock area registry entry."""
    return {
        "area_id": area_id,
        "name": name,
        "floor_id": floor_id,
        "aliases": [],
        "icon": None,
        "picture": None,
        "_instance": instance,
    }


def make_device(
    device_id: str = "abc123",
    name: str = "Living Room Light",
    manufacturer: str = "Philips",
    model: str = "Hue White",
    area_id: str = "living_room",
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock device registry entry."""
    return {
        "id": device_id,
        "name": name,
        "name_by_user": None,
        "manufacturer": manufacturer,
        "model": model,
        "area_id": area_id,
        "disabled_by": None,
        "_instance": instance,
    }


def make_entity_registry(
    entity_id: str = "light.living_room",
    name: str | None = None,
    area_id: str | None = "living_room",
    device_id: str | None = "abc123",
    platform: str = "hue",
    labels: list[str] | None = None,
    instance: str = "default",
) -> dict[str, Any]:
    """Build a mock entity registry entry."""
    return {
        "entity_id": entity_id,
        "name": name,
        "original_name": entity_id.split(".")[1].replace("_", " ").title(),
        "area_id": area_id,
        "device_id": device_id,
        "platform": platform,
        "labels": labels or [],
        "disabled_by": None,
        "hidden_by": None,
        "_instance": instance,
    }
