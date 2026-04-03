"""Tests for ha_blade_mcp.models — providers, gates, scrubbing."""

from __future__ import annotations

import pytest

from ha_blade_mcp.models import (
    is_write_enabled,
    parse_providers,
    require_confirm,
    require_write,
    scrub_credentials,
)


class TestParseProviders:
    def test_single_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local:8123")
        monkeypatch.setenv("HA_TOKEN", "my-token")
        providers = parse_providers()
        assert len(providers) == 1
        assert providers[0].name == "default"
        assert providers[0].url == "http://ha.local:8123"
        assert providers[0].token == "my-token"

    def test_single_provider_strips_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_URL", "http://ha.local:8123/")
        monkeypatch.setenv("HA_TOKEN", "tok")
        providers = parse_providers()
        assert providers[0].url == "http://ha.local:8123"

    def test_multi_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_PROVIDERS", "sb,pad")
        monkeypatch.setenv("HA_SB_URL", "http://sb:8123")
        monkeypatch.setenv("HA_SB_TOKEN", "sb-tok")
        monkeypatch.setenv("HA_PAD_URL", "http://pad:8123")
        monkeypatch.setenv("HA_PAD_TOKEN", "pad-tok")
        providers = parse_providers()
        assert len(providers) == 2
        assert providers[0].name == "sb"
        assert providers[1].name == "pad"

    def test_multi_provider_skips_incomplete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_PROVIDERS", "ok,bad")
        monkeypatch.setenv("HA_OK_URL", "http://ok:8123")
        monkeypatch.setenv("HA_OK_TOKEN", "tok")
        # bad has no token
        monkeypatch.setenv("HA_BAD_URL", "http://bad:8123")
        providers = parse_providers()
        assert len(providers) == 1
        assert providers[0].name == "ok"

    def test_no_config_raises(self) -> None:
        with pytest.raises(ValueError, match="not configured"):
            parse_providers()

    def test_multi_provider_all_incomplete_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_PROVIDERS", "bad")
        monkeypatch.setenv("HA_BAD_URL", "http://bad:8123")
        with pytest.raises(ValueError, match="no providers configured"):
            parse_providers()


class TestWriteGate:
    def test_disabled_by_default(self) -> None:
        assert not is_write_enabled()
        assert require_write() is not None
        assert "disabled" in require_write().lower()  # type: ignore[union-attr]

    def test_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_WRITE_ENABLED", "true")
        assert is_write_enabled()
        assert require_write() is None

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HA_WRITE_ENABLED", "TRUE")
        assert is_write_enabled()


class TestConfirmGate:
    def test_not_confirmed(self) -> None:
        result = require_confirm(False)
        assert result is not None
        assert "confirm" in result.lower()

    def test_confirmed(self) -> None:
        assert require_confirm(True) is None


class TestScrubCredentials:
    def test_scrubs_bearer_token(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.sig"
        result = scrub_credentials(text)
        assert "eyJ" not in result
        assert "****" in result

    def test_scrubs_url_credentials(self) -> None:
        text = "https://user:pass@ha.local:8123/api"
        result = scrub_credentials(text)
        assert "pass" not in result
        assert "****" in result

    def test_scrubs_token_param(self) -> None:
        text = "url?token=abc123&other=ok"
        result = scrub_credentials(text)
        assert "abc123" not in result

    def test_preserves_normal_text(self) -> None:
        text = "Connection failed for sandybay"
        assert scrub_credentials(text) == text
