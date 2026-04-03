"""Tests for ha_blade_mcp.client — HA REST and WebSocket client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from ha_blade_mcp.client import (
    AuthError,
    ConnectionError,
    HAClient,
    HAError,
    NotFoundError,
    _classify_error,
)
from ha_blade_mcp.models import ProviderConfig

# httpx.Response needs a request set for raise_for_status() to work
_FAKE_REQUEST = httpx.Request("GET", "http://test")


class TestClassifyError:
    def test_auth_errors(self) -> None:
        assert isinstance(_classify_error("401 Unauthorized"), AuthError)
        assert isinstance(_classify_error("Forbidden access"), AuthError)
        assert isinstance(_classify_error("Invalid access token"), AuthError)

    def test_not_found(self) -> None:
        assert isinstance(_classify_error("404 Not Found"), NotFoundError)

    def test_connection(self) -> None:
        assert isinstance(_classify_error("Connection refused"), ConnectionError)
        assert isinstance(_classify_error("Request timeout"), ConnectionError)

    def test_generic(self) -> None:
        err = _classify_error("Something went wrong")
        assert isinstance(err, HAError)
        assert not isinstance(err, (AuthError, NotFoundError, ConnectionError))


class TestClientInit:
    def test_single_provider(self, ha_env: None) -> None:
        client = HAClient()
        assert client.provider_names == ["default"]

    def test_multi_provider(self, ha_env_multi: None) -> None:
        client = HAClient()
        assert client.provider_names == ["sandybay", "paddington"]

    def test_resolve_provider_specific(self, ha_env_multi: None) -> None:
        client = HAClient()
        providers = client._resolve_provider("sandybay")
        assert len(providers) == 1
        assert providers[0].name == "sandybay"

    def test_resolve_provider_all(self, ha_env_multi: None) -> None:
        client = HAClient()
        providers = client._resolve_provider(None)
        assert len(providers) == 2

    def test_resolve_provider_unknown(self, ha_env_multi: None) -> None:
        client = HAClient()
        with pytest.raises(HAError, match="Unknown instance"):
            client._resolve_provider("nonexistent")


class TestClientRest:
    @pytest.fixture()
    def client(self, ha_env: None) -> HAClient:
        return HAClient()

    @pytest.fixture()
    def provider(self, client: HAClient) -> ProviderConfig:
        return client._providers[0]

    @pytest.mark.asyncio
    async def test_get_success(self, client: HAClient, provider: ProviderConfig) -> None:
        mock_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json={"message": "API running."},
            headers={"content-type": "application/json"},
        )
        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await client._rest(provider, "GET", "/api/")
            assert result == {"message": "API running."}

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, client: HAClient, provider: ProviderConfig) -> None:
        mock_response = httpx.Response(401, text="Unauthorized")
        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            with pytest.raises(AuthError):
                await client._rest(provider, "GET", "/api/states")

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self, client: HAClient, provider: ProviderConfig) -> None:
        mock_response = httpx.Response(404, text="Not Found")
        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            with pytest.raises(NotFoundError):
                await client._rest(provider, "GET", "/api/states/fake.entity")

    @pytest.mark.asyncio
    async def test_connection_error(self, client: HAClient, provider: ProviderConfig) -> None:
        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.side_effect = httpx.ConnectError("Connection refused")
            with pytest.raises(ConnectionError):
                await client._rest(provider, "GET", "/api/")


class TestClientInfo:
    @pytest.mark.asyncio
    async def test_info_success(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        api_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json={"message": "API running."},
            headers={"content-type": "application/json"},
        )
        config_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json={
                "version": "2025.4.1",
                "location_name": "Home",
                "components": ["light", "switch", "sensor"],
            },
            headers={"content-type": "application/json"},
        )

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.side_effect = [api_response, config_response]
            results = await client.info()
            assert len(results) == 1
            assert results[0]["status"] == "connected"
            assert results[0]["version"] == "2025.4.1"
            assert results[0]["components"] == 3

    @pytest.mark.asyncio
    async def test_info_error(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.side_effect = httpx.ConnectError("refused")
            results = await client.info()
            assert results[0]["status"].startswith("error:")


class TestClientGetState:
    @pytest.mark.asyncio
    async def test_get_state(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        mock_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json={
                "entity_id": "light.living_room",
                "state": "on",
                "attributes": {"brightness": 200},
            },
            headers={"content-type": "application/json"},
        )

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            result = await client.get_state("light.living_room")
            assert result["entity_id"] == "light.living_room"
            assert result["state"] == "on"
            assert result["_instance"] == "default"

    @pytest.mark.asyncio
    async def test_entity_not_found(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        mock_response = httpx.Response(404, text="Not found")

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            with pytest.raises(NotFoundError, match="Entity not found"):
                await client.get_state("fake.entity")


class TestClientCallService:
    @pytest.mark.asyncio
    async def test_call_service(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        mock_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json=[{"entity_id": "light.living_room", "state": "on"}],
            headers={"content-type": "application/json"},
        )

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            results = await client.call_service("light", "turn_on", target={"entity_id": "light.living_room"})
            assert results[0]["changed_states"] == 1


class TestClientHistory:
    @pytest.mark.asyncio
    async def test_get_history(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        mock_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            json=[
                [
                    {"entity_id": "sensor.temp", "state": "18", "last_changed": "2026-04-03T10:00:00"},
                    {"entity_id": "sensor.temp", "state": "19", "last_changed": "2026-04-03T11:00:00"},
                ]
            ],
            headers={"content-type": "application/json"},
        )

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            results = await client.get_history(["sensor.temp"], "2026-04-03T00:00:00")
            assert len(results) == 1
            assert len(results[0]["history"]) == 1
            assert len(results[0]["history"][0]) == 2


class TestClientTemplate:
    @pytest.mark.asyncio
    async def test_render_template(self, ha_env: None) -> None:
        client = HAClient()
        provider = client._providers[0]

        mock_response = httpx.Response(
            200,
            request=_FAKE_REQUEST,
            text="22.5",
            headers={"content-type": "text/plain"},
        )

        with patch.object(client._get_http(provider), "request", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response
            results = await client.render_template("{{ states('sensor.temp') }}")
            assert results[0]["result"] == "22.5"
