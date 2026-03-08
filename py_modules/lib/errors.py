"""RomM API error types for structured error handling."""


class RommApiError(Exception):
    """Base exception for all RomM HTTP API errors."""
    status_code = None

    def __init__(self, message, url=None, method=None):
        self.url = url
        self.method = method
        super().__init__(message)


class RommAuthError(RommApiError):
    """401 Unauthorized — bad credentials."""
    status_code = 401


class RommForbiddenError(RommApiError):
    """403 Forbidden — valid credentials but insufficient permissions."""
    status_code = 403


class RommNotFoundError(RommApiError):
    """404 Not Found — resource does not exist."""
    status_code = 404


class RommConflictError(RommApiError):
    """409 Conflict."""
    status_code = 409


class RommServerError(RommApiError):
    """5xx server errors (500, 502, 503, etc.)."""
    def __init__(self, message, status_code=500, url=None, method=None):
        self.status_code = status_code
        super().__init__(message, url=url, method=method)


class RommConnectionError(RommApiError):
    """Network-level failures: connection refused, DNS failure, reset, etc."""


class RommTimeoutError(RommApiError):
    """Request timed out."""


class RommSSLError(RommApiError):
    """SSL certificate verification failure."""
