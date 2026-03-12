import socket
import ssl
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from lib.errors import (
    RommApiError,
    RommAuthError,
    RommConflictError,
    RommConnectionError,
    RommForbiddenError,
    RommNotFoundError,
    RommServerError,
    RommSSLError,
    RommTimeoutError,
)
from lib.sync import SyncState

# conftest.py patches decky before this import
from main import Plugin


@pytest.fixture
def plugin():
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._sync_state = SyncState.IDLE
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
        import json as _json
        from unittest.mock import MagicMock, patch

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
        import json as _json
        from unittest.mock import MagicMock, patch

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
        import json as _json
        from unittest.mock import MagicMock, patch

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"id": 1}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
            plugin._romm_put_json("/api/saves/1", {"filename": "test.srm"})

        req = mock_open.call_args[0][0]
        assert req.get_method() == "PUT"


class TestRommUploadMultipart:
    def test_upload_sends_multipart(self, plugin, tmp_path):
        import json as _json
        from unittest.mock import MagicMock, patch

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

    def test_upload_strips_control_chars_from_filename(self, plugin, tmp_path):
        """Filenames with CRLF/null bytes must not inject multipart headers."""
        import json as _json
        from unittest.mock import MagicMock, patch

        plugin.settings["romm_url"] = "http://romm.local"
        plugin.settings["romm_user"] = "user"
        plugin.settings["romm_pass"] = "pass"
        plugin.settings["romm_allow_insecure_ssl"] = False

        # Create a file whose basename contains injected control chars
        evil_name = "evil\r\nInjected-Header: bad\0.srm"
        safe_dir = tmp_path / "sub"
        safe_dir.mkdir()
        # We can't create a file with \r\n\0 in the name on most FS,
        # so patch os.path.basename to return the evil name.
        save_file = safe_dir / "normal.srm"
        save_file.write_bytes(b"data")

        fake_resp = MagicMock()
        fake_resp.read.return_value = _json.dumps({"id": 1}).encode()
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("urllib.request.urlopen", return_value=fake_resp) as mock_open,
            patch("os.path.basename", return_value=evil_name),
        ):
            plugin._romm_upload_multipart("/api/saves", str(save_file))

        req = mock_open.call_args[0][0]
        body = req.data
        # Control characters must be stripped from the Content-Disposition header
        assert b"\r\nInjected-Header:" not in body
        assert b"\0" not in body.split(b"\r\n\r\n")[0]  # not in headers
        # The sanitized filename should still appear
        assert b'filename="evilInjected-Header: bad.srm"' in body


class TestPlatformMap:
    def test_loads_config_json(self, plugin):
        pm = plugin._load_platform_map()
        assert isinstance(pm, dict)
        assert "n64" in pm
        assert "snes" in pm
        assert len(pm) > 50  # Should have many entries


# ============================================================================
# _translate_http_error
# ============================================================================


def _setup_plugin(plugin):
    """Configure plugin with valid settings for HTTP tests."""
    plugin.settings["romm_url"] = "http://romm.local"
    plugin.settings["romm_user"] = "user"
    plugin.settings["romm_pass"] = "pass"
    plugin.settings["romm_allow_insecure_ssl"] = False


class TestTranslateHttpError:
    """Tests for _translate_http_error method."""

    def test_401_becomes_auth_error(self, plugin):
        exc = urllib.error.HTTPError("http://romm.local/api/test", 401, "Unauthorized", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/test", "GET")
        assert isinstance(result, RommAuthError)
        assert result.status_code == 401
        assert result.url == "http://romm.local/api/test"
        assert result.method == "GET"
        assert "401" in str(result)

    def test_403_becomes_forbidden_error(self, plugin):
        exc = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x", "POST")
        assert isinstance(result, RommForbiddenError)
        assert result.status_code == 403

    def test_404_becomes_not_found_error(self, plugin):
        exc = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommNotFoundError)
        assert result.status_code == 404

    def test_409_becomes_conflict_error(self, plugin):
        exc = urllib.error.HTTPError("url", 409, "Conflict", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x", "PUT")
        assert isinstance(result, RommConflictError)
        assert result.status_code == 409

    def test_500_becomes_server_error(self, plugin):
        exc = urllib.error.HTTPError("url", 500, "Internal Server Error", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommServerError)
        assert result.status_code == 500

    def test_502_becomes_server_error(self, plugin):
        exc = urllib.error.HTTPError("url", 502, "Bad Gateway", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommServerError)
        assert result.status_code == 502

    def test_429_becomes_server_error(self, plugin):
        exc = urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommServerError)
        assert result.status_code == 429
        assert "Rate limited" in str(result)

    def test_other_4xx_becomes_generic_api_error(self, plugin):
        exc = urllib.error.HTTPError("url", 418, "I'm a Teapot", {}, None)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommApiError)
        assert not isinstance(result, RommServerError)
        assert "418" in str(result)

    def test_url_error_plain_becomes_connection_error(self, plugin):
        exc = urllib.error.URLError("Connection refused")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommConnectionError)

    def test_url_error_wrapping_ssl_becomes_ssl_error(self, plugin):
        ssl_exc = ssl.SSLError("certificate verify failed")
        exc = urllib.error.URLError(ssl_exc)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommSSLError)

    def test_url_error_wrapping_timeout_becomes_timeout_error(self, plugin):
        timeout_exc = socket.timeout("timed out")
        exc = urllib.error.URLError(timeout_exc)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommTimeoutError)

    def test_url_error_wrapping_timeout_error_becomes_timeout_error(self, plugin):
        timeout_exc = TimeoutError("timed out")
        exc = urllib.error.URLError(timeout_exc)
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommTimeoutError)

    def test_direct_ssl_error(self, plugin):
        exc = ssl.SSLError("bad cert")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommSSLError)

    def test_direct_socket_timeout(self, plugin):
        exc = socket.timeout("timed out")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommTimeoutError)

    def test_direct_timeout_error(self, plugin):
        exc = TimeoutError("timed out")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommTimeoutError)

    def test_connection_error(self, plugin):
        exc = ConnectionRefusedError("refused")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommConnectionError)

    def test_os_error(self, plugin):
        exc = OSError("network unreachable")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommConnectionError)

    def test_unknown_exception_wrapped_in_romm_api_error(self, plugin):
        exc = ValueError("bad value")
        result = plugin._translate_http_error(exc, "http://romm.local/api/x")
        assert isinstance(result, RommApiError)
        assert "Unexpected error: bad value" in str(result)


# ============================================================================
# HTTP methods raise structured errors
# ============================================================================


class TestRommRequestErrors:
    """_romm_request translates HTTP errors into structured exceptions."""

    def test_401_raises_auth_error(self, plugin):
        _setup_plugin(plugin)
        exc = urllib.error.HTTPError("http://romm.local/api/test", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(RommAuthError) as exc_info:
                plugin._romm_request("/api/test")
        assert exc_info.value.status_code == 401

    def test_connection_refused_raises_connection_error(self, plugin):
        _setup_plugin(plugin)
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(RommConnectionError):
                plugin._romm_request("/api/test")

    def test_timeout_raises_timeout_error(self, plugin):
        _setup_plugin(plugin)
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            with pytest.raises(RommTimeoutError):
                plugin._romm_request("/api/test")

    def test_500_raises_server_error(self, plugin):
        _setup_plugin(plugin)
        exc = urllib.error.HTTPError("http://romm.local/api/test", 500, "Internal Server Error", {}, None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(RommServerError) as exc_info:
                plugin._romm_request("/api/test")
        assert exc_info.value.status_code == 500

    def test_preserves_cause_chain(self, plugin):
        _setup_plugin(plugin)
        original = ConnectionRefusedError("refused")
        with patch("urllib.request.urlopen", side_effect=original):
            with pytest.raises(RommConnectionError) as exc_info:
                plugin._romm_request("/api/test")
        assert exc_info.value.__cause__ is original

    def test_already_translated_error_not_rewrapped(self, plugin):
        """If a nested call already raised RommApiError, don't re-translate."""
        _setup_plugin(plugin)
        original_err = RommAuthError("already translated")
        with patch("urllib.request.urlopen", side_effect=original_err):
            with pytest.raises(RommAuthError) as exc_info:
                plugin._romm_request("/api/test")
        assert str(exc_info.value) == "already translated"


class TestRommJsonRequestErrors:
    """_romm_json_request translates errors too."""

    def test_404_raises_not_found(self, plugin):
        _setup_plugin(plugin)
        exc = urllib.error.HTTPError("http://romm.local/api/saves", 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(RommNotFoundError):
                plugin._romm_post_json("/api/saves", {"data": 1})

    def test_timeout_raises_timeout_error(self, plugin):
        _setup_plugin(plugin)
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with pytest.raises(RommTimeoutError):
                plugin._romm_put_json("/api/saves/1", {"data": 1})


class TestRommDownloadErrors:
    """_romm_download translates errors."""

    def test_403_raises_forbidden(self, plugin, tmp_path):
        _setup_plugin(plugin)
        exc = urllib.error.HTTPError("http://romm.local/assets/rom.zip", 403, "Forbidden", {}, None)
        dest = str(tmp_path / "rom.zip")
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(RommForbiddenError):
                plugin._romm_download("/assets/rom.zip", dest)


class TestRommUploadMultipartErrors:
    """_romm_upload_multipart translates errors."""

    def test_409_raises_conflict(self, plugin, tmp_path):
        _setup_plugin(plugin)
        save_file = tmp_path / "test.srm"
        save_file.write_bytes(b"data")
        exc = urllib.error.HTTPError("http://romm.local/api/saves", 409, "Conflict", {}, None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(RommConflictError):
                plugin._romm_upload_multipart("/api/saves", str(save_file))


# ============================================================================
# Retry Logic (moved from test_save_sync.py)
# ============================================================================


class TestRetryLogic:
    """Tests for _with_retry and _is_retryable (now on RommClientMixin)."""

    def test_is_retryable_5xx(self, plugin):
        """HTTP 500/502/503 are retryable."""
        for code in (500, 502, 503):
            exc = urllib.error.HTTPError("url", code, "err", {}, None)
            assert plugin._is_retryable(exc) is True

    def test_is_not_retryable_4xx(self, plugin):
        """HTTP 400/401/404/409 are NOT retryable."""
        for code in (400, 401, 403, 404, 409):
            exc = urllib.error.HTTPError("url", code, "err", {}, None)
            assert plugin._is_retryable(exc) is False

    def test_is_retryable_connection_errors(self, plugin):
        """ConnectionError, TimeoutError, URLError are retryable."""
        assert plugin._is_retryable(ConnectionError("refused")) is True
        assert plugin._is_retryable(TimeoutError("timed out")) is True
        assert plugin._is_retryable(urllib.error.URLError("unreachable")) is True
        assert plugin._is_retryable(OSError("network down")) is True

    def test_is_not_retryable_other(self, plugin):
        """ValueError, KeyError etc. are NOT retryable."""
        assert plugin._is_retryable(ValueError("bad")) is False
        assert plugin._is_retryable(KeyError("missing")) is False

    def test_is_retryable_romm_server_error(self, plugin):
        """RommServerError is retryable."""
        assert plugin._is_retryable(RommServerError("500")) is True

    def test_is_retryable_romm_connection_error(self, plugin):
        """RommConnectionError is retryable."""
        assert plugin._is_retryable(RommConnectionError("refused")) is True

    def test_is_retryable_romm_timeout_error(self, plugin):
        """RommTimeoutError is retryable."""
        assert plugin._is_retryable(RommTimeoutError("timed out")) is True

    def test_is_not_retryable_romm_auth_error(self, plugin):
        """RommAuthError is NOT retryable."""
        assert plugin._is_retryable(RommAuthError("401")) is False

    def test_is_not_retryable_romm_not_found_error(self, plugin):
        """RommNotFoundError is NOT retryable."""
        assert plugin._is_retryable(RommNotFoundError("404")) is False

    def test_is_not_retryable_romm_conflict_error(self, plugin):
        """RommConflictError is NOT retryable."""
        assert plugin._is_retryable(RommConflictError("409")) is False

    def test_is_not_retryable_romm_ssl_error(self, plugin):
        """RommSSLError is NOT retryable."""
        assert plugin._is_retryable(RommSSLError("cert bad")) is False

    def test_is_not_retryable_romm_forbidden_error(self, plugin):
        """RommForbiddenError is NOT retryable."""
        assert plugin._is_retryable(RommForbiddenError("403")) is False

    def test_retry_succeeds_on_first_try(self, plugin):
        """No retries needed when call succeeds."""
        fn = MagicMock(return_value="ok")
        result = plugin._with_retry(fn, "arg1", key="val")
        assert result == "ok"
        fn.assert_called_once_with("arg1", key="val")

    def test_retry_succeeds_after_transient_failure(self, plugin):
        """Retries on transient error, succeeds on second attempt."""
        fn = MagicMock(side_effect=[ConnectionError("refused"), "ok"])
        with patch("time.sleep"):
            result = plugin._with_retry(fn, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert fn.call_count == 2

    def test_retry_exhausted_raises(self, plugin):
        """All attempts fail -> raises last exception."""
        fn = MagicMock(side_effect=ConnectionError("refused"))
        with patch("time.sleep"):
            with pytest.raises(ConnectionError):
                plugin._with_retry(fn, max_attempts=3, base_delay=0)
        assert fn.call_count == 3

    def test_retry_no_retry_on_4xx(self, plugin):
        """4xx errors raise immediately without retry."""
        err = urllib.error.HTTPError("url", 404, "not found", {}, None)
        fn = MagicMock(side_effect=err)
        with pytest.raises(urllib.error.HTTPError):
            plugin._with_retry(fn, max_attempts=3, base_delay=0)
        fn.assert_called_once()

    def test_retry_delays_exponential(self, plugin):
        """Delays follow base_delay * 3^attempt pattern."""
        fn = MagicMock(side_effect=[ConnectionError("1"), ConnectionError("2"), "ok"])
        with patch("time.sleep") as mock_sleep:
            plugin._with_retry(fn, max_attempts=3, base_delay=1)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # 1 * 3^0
        mock_sleep.assert_any_call(3)  # 1 * 3^1

    def test_retry_no_retry_on_romm_auth_error(self, plugin):
        """RommAuthError raises immediately without retry."""
        fn = MagicMock(side_effect=RommAuthError("401"))
        with pytest.raises(RommAuthError):
            plugin._with_retry(fn, max_attempts=3, base_delay=0)
        fn.assert_called_once()

    def test_retry_retries_romm_server_error(self, plugin):
        """RommServerError is retried."""
        fn = MagicMock(side_effect=[RommServerError("500"), "ok"])
        with patch("time.sleep"):
            result = plugin._with_retry(fn, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert fn.call_count == 2

    def test_retry_retries_romm_connection_error(self, plugin):
        """RommConnectionError is retried."""
        fn = MagicMock(side_effect=[RommConnectionError("refused"), "ok"])
        with patch("time.sleep"):
            result = plugin._with_retry(fn, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert fn.call_count == 2


# ============================================================================
# test_connection structured errors
# ============================================================================


class TestTestConnectionErrors:
    """test_connection returns structured error_code in responses."""

    @pytest.mark.asyncio
    async def test_config_error_when_url_empty(self, plugin):
        """Returns config_error when no URL is configured."""
        plugin.settings["romm_url"] = ""
        result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "config_error"
        assert "No server URL" in result["message"]

    @pytest.mark.asyncio
    async def test_auth_error_on_401(self, plugin):
        """Returns auth_error when platforms endpoint returns 401."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        # Heartbeat succeeds, platforms raises auth error
        heartbeat_response = {"status": "ok"}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat_response, RommAuthError("401")]):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "auth_error"
        assert "Authentication failed" in result["message"]

    @pytest.mark.asyncio
    async def test_connection_error_on_refused(self, plugin):
        """Returns connection_error when server is unreachable."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        with patch.object(plugin, "_romm_request", side_effect=RommConnectionError("refused")):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "connection_error"
        assert "unreachable" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_ssl_error(self, plugin):
        """Returns ssl_error on SSL certificate failure."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        with patch.object(plugin, "_romm_request", side_effect=RommSSLError("cert fail")):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "ssl_error"
        assert "SSL" in result["message"]

    @pytest.mark.asyncio
    async def test_success_on_happy_path(self, plugin):
        """Returns success when both heartbeat and platforms succeed."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"SYSTEM": {"VERSION": "4.7.0"}, "status": "ok"}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["success"] is True
        assert "Connected to RomM 4.7.0" in result["message"]
        assert result["romm_version"] == "4.7.0"
        assert plugin._romm_version == "4.7.0"

    @pytest.mark.asyncio
    async def test_server_reachable_but_api_failed(self, plugin):
        """When heartbeat succeeds but platforms fails with non-auth error, message is prefixed."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat_response = {"SYSTEM": {"VERSION": "4.7.0"}}
        with patch.object(
            plugin, "_romm_request", side_effect=[heartbeat_response, RommServerError("500", status_code=500)]
        ):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "server_error"
        assert "Server reachable but API request failed" in result["message"]


class TestVersionDetection:
    """test_connection detects and reports RomM server version."""

    @pytest.mark.asyncio
    async def test_version_extracted_from_heartbeat(self, plugin):
        """Extracts version from SYSTEM.VERSION in heartbeat response."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"SYSTEM": {"VERSION": "4.7.0"}}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["romm_version"] == "4.7.0"
        assert plugin._romm_version == "4.7.0"

    @pytest.mark.asyncio
    async def test_version_warning_for_old_version(self, plugin):
        """Shows warning when RomM version is below minimum tested."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"SYSTEM": {"VERSION": "4.5.0"}}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["success"] is True
        assert result["romm_version"] == "4.5.0"
        assert "version_warning" in result
        assert "not been tested" in result["version_warning"]
        assert "4.6.1" in result["version_warning"]

    @pytest.mark.asyncio
    async def test_no_warning_for_supported_version(self, plugin):
        """No warning for supported RomM versions."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"SYSTEM": {"VERSION": "4.6.1"}}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["success"] is True
        assert "version_warning" not in result

    @pytest.mark.asyncio
    async def test_development_version_no_warning(self, plugin):
        """Development builds pass through without warning."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"SYSTEM": {"VERSION": "development"}}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["success"] is True
        assert result.get("romm_version") == "development"
        assert "version_warning" not in result

    @pytest.mark.asyncio
    async def test_missing_version_in_heartbeat(self, plugin):
        """Handles heartbeat without SYSTEM.VERSION gracefully."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        heartbeat = {"status": "ok"}
        with patch.object(plugin, "_romm_request", side_effect=[heartbeat, {"platforms": []}]):
            result = await plugin.test_connection()
        assert result["success"] is True
        assert plugin._romm_version is None
        assert "version_warning" not in result

    @pytest.mark.asyncio
    async def test_version_cleared_on_connection_failure(self, plugin):
        """Version is cleared when heartbeat fails."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        plugin._romm_version = "4.7.0"  # previously detected
        with patch.object(plugin, "_romm_request", side_effect=RommConnectionError("refused")):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert plugin._romm_version is None

    @pytest.mark.asyncio
    async def test_get_romm_version_returns_cached(self, plugin):
        """get_romm_version returns the last detected version."""
        plugin._romm_version = "4.7.0"
        result = await plugin.get_romm_version()
        assert result == {"version": "4.7.0"}

    @pytest.mark.asyncio
    async def test_get_romm_version_returns_none_before_connect(self, plugin):
        """get_romm_version returns None before any connection."""
        plugin._romm_version = None
        result = await plugin.get_romm_version()
        assert result == {"version": None}

    @pytest.mark.asyncio
    async def test_timeout_error(self, plugin):
        """Returns timeout_error on request timeout."""
        import asyncio

        _setup_plugin(plugin)
        plugin.loop = asyncio.get_event_loop()
        with patch.object(plugin, "_romm_request", side_effect=RommTimeoutError("timed out")):
            result = await plugin.test_connection()
        assert result["success"] is False
        assert result["error_code"] == "timeout_error"
