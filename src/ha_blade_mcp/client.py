"""Home Assistant client — REST and WebSocket APIs.

Async client wrapping HA's REST and WebSocket APIs with multi-provider support,
credential scrubbing, and typed exceptions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from ha_blade_mcp.models import ProviderConfig, parse_providers, scrub_credentials

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HAError(Exception):
    """Base exception for Home Assistant client errors."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.details = details


class AuthError(HAError):
    """Authentication failed — invalid or expired token."""


class NotFoundError(HAError):
    """Requested resource not found."""


class ConnectionError(HAError):  # noqa: A001
    """Cannot connect to Home Assistant instance."""


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

_ERROR_PATTERNS: list[tuple[str, type[HAError]]] = [
    ("unauthorized", AuthError),
    ("401", AuthError),
    ("invalid access token", AuthError),
    ("forbidden", AuthError),
    ("403", AuthError),
    ("not found", NotFoundError),
    ("404", NotFoundError),
    ("connection", ConnectionError),
    ("timeout", ConnectionError),
    ("unreachable", ConnectionError),
    ("connect error", ConnectionError),
]


def _classify_error(message: str) -> HAError:
    """Map error message to a typed exception."""
    lower = message.lower()
    for pattern, exc_cls in _ERROR_PATTERNS:
        if pattern in lower:
            return exc_cls(scrub_credentials(message))
    return HAError(scrub_credentials(message))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HAClient:
    """Multi-provider Home Assistant client.

    Manages httpx clients for REST and websockets connections for WS,
    one per provider. WebSocket connections are lazy-initialized.
    """

    def __init__(self) -> None:
        self._providers = parse_providers()
        self._http: dict[str, httpx.AsyncClient] = {}
        self._ws: dict[str, ClientConnection] = {}
        self._ws_id: dict[str, int] = {}
        self._ws_lock: dict[str, asyncio.Lock] = {}

    @property
    def provider_names(self) -> list[str]:
        """Return configured provider names."""
        return [p.name for p in self._providers]

    def _get_http(self, provider: ProviderConfig) -> httpx.AsyncClient:
        """Get or create an httpx client for a provider."""
        if provider.name not in self._http:
            self._http[provider.name] = httpx.AsyncClient(
                base_url=provider.url,
                headers={
                    "Authorization": f"Bearer {provider.token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._http[provider.name]

    def _resolve_provider(self, instance: str | None) -> list[ProviderConfig]:
        """Resolve instance name to provider configs."""
        if instance:
            for p in self._providers:
                if p.name == instance:
                    return [p]
            available = ", ".join(p.name for p in self._providers)
            raise HAError(f"Unknown instance: {instance}. Available: {available}")
        return self._providers

    # -----------------------------------------------------------------------
    # REST transport
    # -----------------------------------------------------------------------

    async def _rest(self, provider: ProviderConfig, method: str, path: str, **kwargs: Any) -> Any:
        """Execute a REST API call."""
        try:
            client = self._get_http(provider)
            response = await client.request(method, path, **kwargs)
            if response.status_code == 401:
                raise AuthError(f"Authentication failed for {provider.name}")
            if response.status_code == 404:
                raise NotFoundError(f"Not found: {path}")
            response.raise_for_status()
            ct = response.headers.get("content-type", "")
            if ct.startswith("application/json"):
                return response.json()
            return response.text
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise ConnectionError(scrub_credentials(f"Connection failed for {provider.name}: {e}")) from e
        except httpx.HTTPStatusError as e:
            raise _classify_error(str(e)) from e

    # -----------------------------------------------------------------------
    # WebSocket transport
    # -----------------------------------------------------------------------

    async def _ws_connect(self, provider: ProviderConfig) -> ClientConnection:
        """Establish and authenticate a WebSocket connection."""
        ws_url = provider.url.replace("https://", "wss://").replace("http://", "ws://")
        ws = await websockets.connect(f"{ws_url}/api/websocket")
        # auth_required
        msg = json.loads(await ws.recv())
        if msg.get("type") != "auth_required":
            raise HAError(f"Unexpected WS message from {provider.name}: {msg.get('type')}")
        # Send auth
        await ws.send(json.dumps({"type": "auth", "access_token": provider.token}))
        msg = json.loads(await ws.recv())
        if msg.get("type") == "auth_invalid":
            await ws.close()
            raise AuthError(f"WebSocket auth failed for {provider.name}")
        if msg.get("type") != "auth_ok":
            await ws.close()
            raise HAError(f"Unexpected auth response from {provider.name}: {msg.get('type')}")
        logger.debug("WebSocket connected to %s (HA %s)", provider.name, msg.get("ha_version"))
        return ws

    async def _get_ws(self, provider: ProviderConfig) -> ClientConnection:
        """Get or create a WebSocket connection for a provider."""
        if provider.name not in self._ws_lock:
            self._ws_lock[provider.name] = asyncio.Lock()

        async with self._ws_lock[provider.name]:
            ws = self._ws.get(provider.name)
            if ws is None or ws.close_code is not None:
                ws = await self._ws_connect(provider)
                self._ws[provider.name] = ws
                self._ws_id[provider.name] = 1
        return ws

    async def _ws_call(self, provider: ProviderConfig, msg_type: str, **kwargs: Any) -> Any:
        """Send a WebSocket command and wait for the response."""
        ws = await self._get_ws(provider)

        if provider.name not in self._ws_lock:
            self._ws_lock[provider.name] = asyncio.Lock()

        async with self._ws_lock[provider.name]:
            msg_id = self._ws_id.get(provider.name, 1)
            self._ws_id[provider.name] = msg_id + 1

        message = {"id": msg_id, "type": msg_type, **kwargs}
        await ws.send(json.dumps(message))

        # Wait for response with matching ID, discard others
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
            response = json.loads(raw)
            if response.get("id") == msg_id:
                if not response.get("success", True):
                    error = response.get("error", {})
                    raise HAError(f"WS error ({provider.name}): {error.get('message', 'Unknown error')}")
                return response.get("result")

    # -----------------------------------------------------------------------
    # Info
    # -----------------------------------------------------------------------

    async def info(self, instance: str | None = None) -> list[dict[str, Any]]:
        """Health check: connection status, version, component count."""
        results = []
        for p in self._resolve_provider(instance):
            try:
                await self._rest(p, "GET", "/api/")
                config = await self._rest(p, "GET", "/api/config")
                results.append(
                    {
                        "instance": p.name,
                        "status": "connected",
                        "version": config.get("version", "unknown"),
                        "location_name": config.get("location_name", ""),
                        "components": len(config.get("components", [])),
                    }
                )
            except HAError as e:
                results.append({"instance": p.name, "status": f"error: {scrub_credentials(str(e))}"})
        return results

    async def config(self, instance: str | None = None) -> list[dict[str, Any]]:
        """System configuration: location, units, timezone."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._rest(p, "GET", "/api/config")
            results.append(
                {
                    "instance": p.name,
                    "version": data.get("version"),
                    "location_name": data.get("location_name"),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude"),
                    "elevation": data.get("elevation"),
                    "unit_system": data.get("unit_system", {}).get("temperature"),
                    "currency": data.get("currency"),
                    "time_zone": data.get("time_zone"),
                    "components_count": len(data.get("components", [])),
                }
            )
        return results

    async def error_log(self, instance: str | None = None, lines: int = 50) -> list[dict[str, Any]]:
        """Recent error log entries."""
        results = []
        for p in self._resolve_provider(instance):
            text = await self._rest(p, "GET", "/api/error_log")
            log_lines = text.strip().split("\n") if isinstance(text, str) and text.strip() else []
            results.append(
                {
                    "instance": p.name,
                    "lines": log_lines[-lines:] if len(log_lines) > lines else log_lines,
                }
            )
        return results

    # -----------------------------------------------------------------------
    # States
    # -----------------------------------------------------------------------

    async def get_state(self, entity_id: str, instance: str | None = None) -> dict[str, Any]:
        """Get current state of a single entity."""
        for p in self._resolve_provider(instance):
            try:
                data: dict[str, Any] = await self._rest(p, "GET", f"/api/states/{entity_id}")
                data["_instance"] = p.name
                return data
            except NotFoundError:
                continue
        raise NotFoundError(f"Entity not found: {entity_id}")

    async def get_states(self, entity_ids: list[str], instance: str | None = None) -> list[dict[str, Any]]:
        """Get states for multiple entities in one call."""
        results = []
        id_set = set(entity_ids)
        for p in self._resolve_provider(instance):
            all_states = await self._rest(p, "GET", "/api/states")
            for s in all_states:
                if s["entity_id"] in id_set:
                    s["_instance"] = p.name
                    results.append(s)
        return results

    async def get_states_by_domain(
        self,
        domain: str,
        instance: str | None = None,
        area: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get all entity states in a domain, optionally filtered by area.

        Returns (results, matched_total) where matched_total is the count
        of entities that match the domain/area predicates across all providers
        BEFORE the limit truncation is applied (i.e. matched_total >= len(results)).
        """
        results: list[dict[str, Any]] = []
        matched_total = 0
        for p in self._resolve_provider(instance):
            all_states = await self._rest(p, "GET", "/api/states")

            # If area filter, resolve entity→area mapping via WS registry
            area_map: dict[str, str | None] = {}
            if area:
                try:
                    entities = await self._ws_call(p, "config/entity_registry/list")
                    area_map = {e["entity_id"]: e.get("area_id") for e in entities}
                except HAError:
                    logger.warning("Could not fetch entity registry for area filter on %s", p.name)

            for s in all_states:
                eid = s.get("entity_id", "")
                if not eid.startswith(f"{domain}."):
                    continue
                if area and area_map.get(eid) != area:
                    continue
                matched_total += 1
                if len(results) < limit:
                    s["_instance"] = p.name
                    results.append(s)
        return results, matched_total

    # -----------------------------------------------------------------------
    # History
    # -----------------------------------------------------------------------

    async def get_history(
        self,
        entity_ids: list[str],
        start: str,
        end: str | None = None,
        instance: str | None = None,
        minimal: bool = True,
    ) -> list[dict[str, Any]]:
        """State history for entities in a time range."""
        results = []
        for p in self._resolve_provider(instance):
            params: dict[str, str] = {
                "filter_entity_id": ",".join(entity_ids),
                "minimal_response": str(minimal).lower(),
            }
            if end:
                params["end_time"] = end
            data = await self._rest(p, "GET", f"/api/history/period/{start}", params=params)
            results.append({"instance": p.name, "history": data if isinstance(data, list) else []})
        return results

    async def get_logbook(
        self,
        start: str,
        end: str | None = None,
        entity_id: str | None = None,
        instance: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Logbook entries for a time range."""
        results: list[dict[str, Any]] = []
        for p in self._resolve_provider(instance):
            params: dict[str, str] = {}
            if end:
                params["end_time"] = end
            if entity_id:
                params["entity"] = entity_id
            data = await self._rest(p, "GET", f"/api/logbook/{start}", params=params)
            entries = data[:limit] if isinstance(data, list) else []
            for e in entries:
                e["_instance"] = p.name
            results.extend(entries)
        return results[:limit]

    # -----------------------------------------------------------------------
    # Templates
    # -----------------------------------------------------------------------

    async def render_template(self, template: str, instance: str | None = None) -> list[dict[str, Any]]:
        """Render a Jinja2 template server-side."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._rest(p, "POST", "/api/template", json={"template": template})
            results.append({"instance": p.name, "result": data})
        return results

    # -----------------------------------------------------------------------
    # Services
    # -----------------------------------------------------------------------

    async def list_services(self, instance: str | None = None, domain: str | None = None) -> list[dict[str, Any]]:
        """List available service domains and their services."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._rest(p, "GET", "/api/services")
            if domain:
                data = [d for d in data if d.get("domain") == domain]
            results.append({"instance": p.name, "services": data})
        return results

    async def call_service(
        self,
        domain: str,
        service: str,
        instance: str | None = None,
        target: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Call a Home Assistant service."""
        results = []
        for p in self._resolve_provider(instance):
            body: dict[str, Any] = {}
            if target:
                body.update(target)
            if data:
                body.update(data)
            resp = await self._rest(p, "POST", f"/api/services/{domain}/{service}", json=body)
            results.append(
                {
                    "instance": p.name,
                    "changed_states": len(resp) if isinstance(resp, list) else 0,
                }
            )
        return results

    # -----------------------------------------------------------------------
    # Calendar
    # -----------------------------------------------------------------------

    async def list_calendars(self, instance: str | None = None) -> list[dict[str, Any]]:
        """List calendar entities."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._rest(p, "GET", "/api/calendars")
            for cal in data:
                cal["_instance"] = p.name
            results.extend(data)
        return results

    async def get_calendar_events(
        self, entity_id: str, start: str, end: str, instance: str | None = None
    ) -> list[dict[str, Any]]:
        """Get events from a calendar entity."""
        results = []
        for p in self._resolve_provider(instance):
            try:
                data = await self._rest(p, "GET", f"/api/calendars/{entity_id}", params={"start": start, "end": end})
                for event in data:
                    event["_instance"] = p.name
                results.extend(data)
            except NotFoundError:
                continue
        return results

    # -----------------------------------------------------------------------
    # Automations
    # -----------------------------------------------------------------------

    async def list_automations(self, instance: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List automation entities with state."""
        records, _ = await self.get_states_by_domain("automation", instance=instance, limit=limit)
        return records

    async def get_automation_config(self, automation_id: str, instance: str | None = None) -> dict[str, Any]:
        """Get full YAML config of an automation."""
        for p in self._resolve_provider(instance):
            try:
                data: dict[str, Any] = await self._rest(p, "GET", f"/api/config/automation/config/{automation_id}")
                data["_instance"] = p.name
                return data
            except NotFoundError:
                continue
        raise NotFoundError(f"Automation not found: {automation_id}")

    async def create_automation(
        self, automation_id: str, config: dict[str, Any], instance: str | None = None
    ) -> dict[str, Any]:
        """Create or update an automation."""
        providers = self._resolve_provider(instance)
        p = providers[0]
        await self._rest(p, "POST", f"/api/config/automation/config/{automation_id}", json=config)
        return {"instance": p.name, "automation_id": automation_id, "status": "created"}

    async def delete_automation(self, automation_id: str, instance: str | None = None) -> dict[str, Any]:
        """Delete an automation."""
        providers = self._resolve_provider(instance)
        p = providers[0]
        await self._rest(p, "DELETE", f"/api/config/automation/config/{automation_id}")
        return {"instance": p.name, "automation_id": automation_id, "status": "deleted"}

    # -----------------------------------------------------------------------
    # Scripts / Scenes
    # -----------------------------------------------------------------------

    async def list_scripts(self, instance: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List script entities."""
        records, _ = await self.get_states_by_domain("script", instance=instance, limit=limit)
        return records

    async def run_script(
        self, script_id: str, variables: dict[str, Any] | None = None, instance: str | None = None
    ) -> dict[str, Any]:
        """Run a script with optional variables."""
        providers = self._resolve_provider(instance)
        p = providers[0]
        body = variables or {}
        await self._rest(p, "POST", f"/api/services/script/{script_id}", json=body)
        return {"instance": p.name, "script": script_id, "status": "started"}

    async def list_scenes(self, instance: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List scene entities."""
        records, _ = await self.get_states_by_domain("scene", instance=instance, limit=limit)
        return records

    # -----------------------------------------------------------------------
    # WebSocket: Registry
    # -----------------------------------------------------------------------

    async def list_areas(self, instance: str | None = None) -> list[dict[str, Any]]:
        """List all areas via WebSocket registry."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "config/area_registry/list")
            for area in data:
                area["_instance"] = p.name
            results.extend(data)
        return results

    async def list_devices(
        self,
        instance: str | None = None,
        area: str | None = None,
        manufacturer: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """List devices via WebSocket registry.

        Returns (results, matched_total) where matched_total is the count
        of devices that match the area/manufacturer predicates across all
        providers BEFORE the limit truncation is applied.
        """
        results: list[dict[str, Any]] = []
        matched_total = 0
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "config/device_registry/list")
            for device in data:
                if area and device.get("area_id") != area:
                    continue
                if manufacturer and (device.get("manufacturer") or "").lower() != manufacturer.lower():
                    continue
                matched_total += 1
                if len(results) < limit:
                    device["_instance"] = p.name
                    results.append(device)
        return results, matched_total

    async def list_entities_registry(
        self,
        instance: str | None = None,
        domain: str | None = None,
        area: str | None = None,
        label: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """List entities via WebSocket registry (more metadata than states).

        Returns (results, matched_total) where matched_total is the count
        of entities that match the domain/area/label predicates across all
        providers BEFORE the limit truncation is applied.
        """
        results: list[dict[str, Any]] = []
        matched_total = 0
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "config/entity_registry/list")
            for entity in data:
                eid = entity.get("entity_id", "")
                if domain and not eid.startswith(f"{domain}."):
                    continue
                if area and entity.get("area_id") != area:
                    continue
                if label and label not in entity.get("labels", []):
                    continue
                matched_total += 1
                if len(results) < limit:
                    entity["_instance"] = p.name
                    results.append(entity)
        return results, matched_total

    async def list_floors(self, instance: str | None = None) -> list[dict[str, Any]]:
        """List floors via WebSocket registry."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "config/floor_registry/list")
            for floor in data:
                floor["_instance"] = p.name
            results.extend(data)
        return results

    async def list_labels(self, instance: str | None = None) -> list[dict[str, Any]]:
        """List labels via WebSocket registry."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "config/label_registry/list")
            for lb in data:
                lb["_instance"] = p.name
            results.extend(data)
        return results

    async def search_related(self, item_type: str, item_id: str, instance: str | None = None) -> list[dict[str, Any]]:
        """Find related entities/devices/areas for a given item."""
        results = []
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "search/related", item_type=item_type, item_id=item_id)
            data["_instance"] = p.name
            results.append(data)
        return results

    # -----------------------------------------------------------------------
    # WebSocket: Statistics
    # -----------------------------------------------------------------------

    async def get_statistics(
        self,
        entity_ids: list[str],
        start: str,
        end: str | None = None,
        period: str = "hour",
        types: list[str] | None = None,
        instance: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get recorder statistics for entities.

        Returns (results, matched_total) where matched_total is the count
        of statistic_id keys returned by HA across all providers. There is
        no limit truncation on this tool — returned == matched_total.
        """
        results: list[dict[str, Any]] = []
        matched_total = 0
        kwargs: dict[str, Any] = {
            "start_time": start,
            "statistic_ids": entity_ids,
            "period": period,
        }
        if end:
            kwargs["end_time"] = end
        if types:
            kwargs["types"] = types
        for p in self._resolve_provider(instance):
            data = await self._ws_call(p, "recorder/statistics_during_period", **kwargs)
            if isinstance(data, dict):
                matched_total += len(data)
            results.append({"instance": p.name, "statistics": data})
        return results, matched_total

    async def list_statistic_ids(
        self, instance: str | None = None, statistic_type: str | None = None
    ) -> list[dict[str, Any]]:
        """List available statistic IDs."""
        results = []
        for p in self._resolve_provider(instance):
            kwargs: dict[str, Any] = {}
            if statistic_type:
                kwargs["statistic_type"] = statistic_type
            data = await self._ws_call(p, "recorder/list_statistic_ids", **kwargs)
            for stat in data:
                stat["_instance"] = p.name
            results.extend(data)
        return results

    # -----------------------------------------------------------------------
    # Webhooks
    # -----------------------------------------------------------------------

    async def fire_webhook(
        self, webhook_id: str, data: dict[str, Any] | None = None, instance: str | None = None
    ) -> dict[str, Any]:
        """Fire a webhook on the HA instance."""
        providers = self._resolve_provider(instance)
        p = providers[0]
        body = data or {}
        await self._rest(p, "POST", f"/api/webhook/{webhook_id}", json=body)
        return {"instance": p.name, "webhook_id": webhook_id, "status": "fired"}

    # -----------------------------------------------------------------------
    # Camera
    # -----------------------------------------------------------------------

    async def camera_snapshot_url(self, entity_id: str, instance: str | None = None) -> dict[str, Any]:
        """Return camera proxy URL (token-efficient — URL, not image bytes)."""
        for p in self._resolve_provider(instance):
            return {
                "instance": p.name,
                "entity_id": entity_id,
                "proxy_url": f"{p.url}/api/camera_proxy/{entity_id}",
                "note": "URL requires HA Bearer token to access",
            }
        raise NotFoundError(f"No instance available for camera: {entity_id}")

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    async def close(self) -> None:
        """Close all HTTP and WebSocket connections."""
        for client in self._http.values():
            await client.aclose()
        for ws in self._ws.values():
            try:
                await ws.close()
            except Exception:
                pass
        self._http.clear()
        self._ws.clear()
        self._ws_id.clear()
