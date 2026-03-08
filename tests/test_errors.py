import pytest

from lib.errors import (
    RommApiError,
    RommAuthError,
    RommConflictError,
    RommConnectionError,
    RommForbiddenError,
    RommNotFoundError,
    RommSSLError,
    RommServerError,
    RommTimeoutError,
)


class TestExceptionHierarchy:
    """All custom exceptions inherit from RommApiError and Exception."""

    def test_romm_api_error_is_exception(self):
        assert issubclass(RommApiError, Exception)

    @pytest.mark.parametrize("cls", [
        RommAuthError, RommForbiddenError, RommNotFoundError,
        RommConflictError, RommServerError, RommConnectionError,
        RommTimeoutError, RommSSLError,
    ])
    def test_subclass_is_romm_api_error(self, cls):
        exc = cls("test") if cls is not RommServerError else cls("test", status_code=500)
        assert isinstance(exc, RommApiError)
        assert isinstance(exc, Exception)

    @pytest.mark.parametrize("cls", [
        RommAuthError, RommForbiddenError, RommNotFoundError,
        RommConflictError, RommServerError, RommConnectionError,
        RommTimeoutError, RommSSLError,
    ])
    def test_subclass_caught_by_romm_api_error(self, cls):
        exc = cls("test") if cls is not RommServerError else cls("test", status_code=502)
        with pytest.raises(RommApiError):
            raise exc


class TestExceptionAttributes:
    """Each exception stores message, url, and method."""

    def test_base_error_attributes(self):
        exc = RommApiError("something failed", url="http://romm/api/test", method="GET")
        assert str(exc) == "something failed"
        assert exc.url == "http://romm/api/test"
        assert exc.method == "GET"
        assert exc.status_code is None

    def test_base_error_defaults(self):
        exc = RommApiError("msg")
        assert exc.url is None
        assert exc.method is None

    def test_auth_error_status(self):
        exc = RommAuthError("unauthorized", url="/api/test", method="GET")
        assert exc.status_code == 401
        assert str(exc) == "unauthorized"
        assert exc.url == "/api/test"
        assert exc.method == "GET"

    def test_forbidden_error_status(self):
        exc = RommForbiddenError("forbidden")
        assert exc.status_code == 403

    def test_not_found_error_status(self):
        exc = RommNotFoundError("missing")
        assert exc.status_code == 404

    def test_conflict_error_status(self):
        exc = RommConflictError("conflict")
        assert exc.status_code == 409

    def test_server_error_default_status(self):
        exc = RommServerError("internal error")
        assert exc.status_code == 500

    def test_server_error_custom_status(self):
        exc = RommServerError("bad gateway", status_code=502)
        assert exc.status_code == 502

    def test_server_error_503(self):
        exc = RommServerError("service unavailable", status_code=503, url="/api/x", method="POST")
        assert exc.status_code == 503
        assert exc.url == "/api/x"
        assert exc.method == "POST"

    def test_connection_error_no_status(self):
        exc = RommConnectionError("refused")
        assert exc.status_code is None

    def test_timeout_error_no_status(self):
        exc = RommTimeoutError("timed out")
        assert exc.status_code is None

    def test_ssl_error_no_status(self):
        exc = RommSSLError("cert invalid")
        assert exc.status_code is None


class TestExceptionMessage:
    """Exception messages are accessible via str()."""

    def test_message_preserved(self):
        exc = RommAuthError("HTTP 401: Unauthorized (GET /api/test)")
        assert "401" in str(exc)
        assert "Unauthorized" in str(exc)

    def test_server_error_message(self):
        exc = RommServerError("HTTP 502: Bad Gateway (GET /api/heartbeat)", status_code=502)
        assert "502" in str(exc)
        assert "Bad Gateway" in str(exc)
