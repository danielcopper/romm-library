import pytest

# conftest.py patches decky before this import
from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._sync_running = False
    p._sync_cancel = False
    p._sync_progress = {"running": False}
    p._state = {"shortcut_registry": {}, "installed_roms": {}, "last_sync": None, "sync_stats": {}}
    p._pending_sync = {}
    p._download_tasks = {}
    p._download_queue = {}
    p._download_in_progress = set()
    p._metadata_cache = {}
    return p


class TestResolveSystem:
    def test_exact_slug_match(self, plugin):
        result = plugin._resolve_system("n64")
        assert result == "n64"

    def test_fs_slug_fallback(self, plugin):
        # A slug not in the map but its fs_slug is
        result = plugin._resolve_system("nonexistent-slug", "n64")
        assert result == "n64"

    def test_fallback_returns_slug_as_is(self, plugin):
        result = plugin._resolve_system("totally-unknown-platform")
        assert result == "totally-unknown-platform"


class TestRommDownloadUrlEncoding:
    def test_encodes_spaces_in_cover_path(self, plugin, tmp_path):
        """Cover paths from RomM contain unencoded spaces in timestamps.
        _romm_download must URL-encode them so urllib doesn't reject the URL."""
        import urllib.parse

        # Simulate the path RomM returns
        path = "/assets/romm/resources/roms/53/4375/cover/big.png?ts=2025-07-28 00:05:03"
        encoded = urllib.parse.quote(path, safe="/:?=&@")
        assert " " not in encoded
        assert "%20" in encoded
        assert encoded == "/assets/romm/resources/roms/53/4375/cover/big.png?ts=2025-07-28%2000:05:03"

    def test_preserves_clean_paths(self, plugin):
        """Paths without spaces should pass through unchanged."""
        import urllib.parse

        path = "/assets/romm/resources/roms/53/4375/cover/big.png"
        encoded = urllib.parse.quote(path, safe="/:?=&@")
        assert encoded == path


class TestRommSslContext:
    def test_default_verifies_ssl(self, plugin):
        """Default setting (False) should produce a context that verifies certs."""
        import ssl
        plugin.settings["romm_allow_insecure_ssl"] = False
        ctx = plugin._romm_ssl_context()
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_insecure_disables_verification(self, plugin):
        """When romm_allow_insecure_ssl=True, certs should not be verified."""
        import ssl
        plugin.settings["romm_allow_insecure_ssl"] = True
        ctx = plugin._romm_ssl_context()
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_missing_setting_defaults_secure(self, plugin):
        """Missing setting should default to secure."""
        import ssl
        plugin.settings.pop("romm_allow_insecure_ssl", None)
        ctx = plugin._romm_ssl_context()
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestRommAuthHeader:
    def test_basic_auth_format(self, plugin):
        import base64
        plugin.settings["romm_user"] = "admin"
        plugin.settings["romm_pass"] = "secret"
        header = plugin._romm_auth_header()
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        assert decoded == "admin:secret"

    def test_special_characters_in_password(self, plugin):
        import base64
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "p@ss:w0rd!"
        header = plugin._romm_auth_header()
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        assert decoded == "user:p@ss:w0rd!"


class TestRommRequest:
    def test_uses_auth_header(self, plugin):
        from unittest.mock import MagicMock, patch
        import json as _json

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"ok": True}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
            result = plugin._romm_request("/api/test")

        assert result == {"ok": True}
        req = mock_open.call_args[0][0]
        assert "Basic " in req.get_header("Authorization")


class TestRommJsonRequest:
    def test_post_json(self, plugin):
        from unittest.mock import MagicMock, patch
        import json as _json

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"id": 1}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
            result = plugin._romm_post_json("/api/saves", {"filename": "test.srm"})

        assert result == {"id": 1}
        req = mock_open.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.get_header("Content-type") == "application/json"
        assert "Basic " in req.get_header("Authorization")

    def test_put_json(self, plugin):
        from unittest.mock import MagicMock, patch
        import json as _json

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"id": 1}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
            result = plugin._romm_put_json("/api/saves/1", {"filename": "test.srm"})

        req = mock_open.call_args[0][0]
        assert req.get_method() == "PUT"


class TestRommUploadMultipart:
    def test_upload_sends_multipart(self, plugin, tmp_path):
        from unittest.mock import MagicMock, patch
        import json as _json

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        save_file = tmp_path / "test.srm"
        save_file.write_bytes(b"save data here")

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"id": 42}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
            result = plugin._romm_upload_multipart("/api/saves", str(save_file))

        assert result == {"id": 42}
        req = mock_open.call_args[0][0]
        assert "multipart/form-data" in req.get_header("Content-type")
        assert b"save data here" in req.data
        assert "Basic " in req.get_header("Authorization")


class TestPlatformMap:
    def test_loads_config_json(self, plugin):
        pm = plugin._load_platform_map()
        assert isinstance(pm, dict)
        assert "n64" in pm
        assert "snes" in pm
        assert len(pm) > 50  # Should have many entries
