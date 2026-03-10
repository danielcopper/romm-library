import os
import json
import base64
import socket
import ssl
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

import decky

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

try:
    import certifi
    def _ca_bundle():
        return certifi.where()
except ImportError:
    def _ca_bundle():
        return None

if TYPE_CHECKING:
    from typing import Protocol

    class _RommClientDeps(Protocol):
        settings: dict


class RommClientMixin:
    def _load_platform_map(self):
        # Check plugin root first (Decky CLI moves defaults/ contents to root),
        # then defaults/ subdirectory (dev deploys via mise run deploy)
        root_path = os.path.join(decky.DECKY_PLUGIN_DIR, "config.json")
        dev_path = os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "config.json")
        config_path = root_path if os.path.exists(root_path) else dev_path
        with open(config_path, "r") as f:
            config = json.load(f)
        return config.get("platform_map", {})

    def _resolve_system(self, platform_slug, platform_fs_slug=None):
        if not hasattr(self, '_platform_map'):
            self._platform_map = self._load_platform_map()
        platform_map = self._platform_map
        if platform_slug in platform_map:
            return platform_map[platform_slug]
        if platform_fs_slug and platform_fs_slug in platform_map:
            return platform_map[platform_fs_slug]
        return platform_slug

    def _romm_ssl_context(self):
        """SSL context for RomM connections. Respects user insecure toggle."""
        ctx = ssl.create_default_context(cafile=_ca_bundle())
        if self.settings.get("romm_allow_insecure_ssl", False):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _romm_auth_header(self):
        """Base64-encoded Basic Auth header value for RomM."""
        credentials = base64.b64encode(
            f"{self.settings['romm_user']}:{self.settings['romm_pass']}".encode()
        ).decode()
        return f"Basic {credentials}"

    def _translate_http_error(self, exc, url, method="GET"):
        """Translate urllib/socket exceptions into RommApiError subclasses."""
        # HTTPError first (most specific HTTP-level error)
        if isinstance(exc, urllib.error.HTTPError):
            msg = f"HTTP {exc.code}: {exc.reason} ({method} {url})"
            if exc.code == 401:
                return RommAuthError(msg, url=url, method=method)
            if exc.code == 403:
                return RommForbiddenError(msg, url=url, method=method)
            if exc.code == 404:
                return RommNotFoundError(msg, url=url, method=method)
            if exc.code == 409:
                return RommConflictError(msg, url=url, method=method)
            if exc.code >= 500:
                return RommServerError(msg, status_code=exc.code, url=url, method=method)
            return RommApiError(msg, url=url, method=method)
        # URLError can wrap ssl/timeout in .reason — unwrap first
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                return RommSSLError(str(reason), url=url, method=method)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                return RommTimeoutError(str(reason), url=url, method=method)
            return RommConnectionError(str(exc), url=url, method=method)
        # Direct ssl/timeout/connection (not wrapped in URLError)
        if isinstance(exc, ssl.SSLError):
            return RommSSLError(str(exc), url=url, method=method)
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return RommTimeoutError(str(exc), url=url, method=method)
        if isinstance(exc, (ConnectionError, OSError)):
            return RommConnectionError(str(exc), url=url, method=method)
        return RommApiError(f"Unexpected error: {exc}", url=url, method=method)

    @staticmethod
    def _is_retryable(exc):
        """Check if an exception is a transient error worth retrying."""
        if isinstance(exc, (RommServerError, RommConnectionError, RommTimeoutError)):
            return True
        # Backward compat for non-RomM exceptions
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code >= 500
        if isinstance(exc, (urllib.error.URLError, ConnectionError, TimeoutError, OSError)):
            return True
        return False

    def _with_retry(self, fn, *args, max_attempts=3, base_delay=1, **kwargs):
        """Call fn(*args, **kwargs) with exponential backoff retry.

        Delays: base_delay * 3^attempt (1s, 3s, 9s for defaults).
        Only retries on transient errors (see _is_retryable).
        """
        last_exc = None
        for attempt in range(max_attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts - 1 and self._is_retryable(exc):
                    delay = base_delay * (3 ** attempt)
                    decky.logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay}s: {exc}"
                    )
                    time.sleep(delay)
                else:
                    raise
        raise last_exc  # pragma: no cover

    def _romm_request(self, path):
        url = self.settings["romm_url"].rstrip("/") + path

        def _do_request():
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", self._romm_auth_header())
            try:
                with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except RommApiError:
                raise
            except Exception as exc:
                raise self._translate_http_error(exc, url, "GET") from exc

        return self._with_retry(_do_request)

    def _romm_download(self, path, dest, progress_callback=None):
        encoded_path = urllib.parse.quote(path, safe="/:?=&@")
        url = self.settings["romm_url"].rstrip("/") + encoded_path
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        def _do_download():
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", self._romm_auth_header())
            ctx = self._romm_ssl_context()
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    total = resp.headers.get("Content-Length")
                    total = int(total) if total else 0
                    downloaded = 0
                    block_size = 8192
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = resp.read(block_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total:
                                progress_callback(downloaded, total)
                if total > 0 and downloaded != total:
                    raise IOError(f"Download incomplete: got {downloaded} bytes, expected {total}")
                if total == 0 and downloaded == 0:
                    raise IOError("Download produced 0 bytes (no Content-Length header and no data received)")
            except RommApiError:
                raise
            except Exception as exc:
                raise self._translate_http_error(exc, url, "GET") from exc

        return self._with_retry(_do_download)

    def _romm_json_request(self, path, data, method="POST"):
        """Send a JSON request (POST/PUT) to RomM API, return parsed response."""
        url = self.settings["romm_url"].rstrip("/") + path

        def _do_json_request():
            body = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", self._romm_auth_header())
            try:
                with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except RommApiError:
                raise
            except Exception as exc:
                raise self._translate_http_error(exc, url, method) from exc

        return self._with_retry(_do_json_request)

    def _romm_post_json(self, path, data):
        """POST JSON to RomM API, return parsed response."""
        return self._romm_json_request(path, data, method="POST")

    def _romm_put_json(self, path, data):
        """PUT JSON to RomM API, return parsed response."""
        return self._romm_json_request(path, data, method="PUT")

    def _romm_upload_multipart(self, path, file_path, method="POST"):
        """Upload a file via multipart/form-data to RomM API."""
        boundary = uuid.uuid4().hex
        filename = os.path.basename(file_path)
        safe_filename = filename.replace('"', '\\"')

        with open(file_path, "rb") as f:
            file_data = f.read()

        body = b""
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="saveFile"; filename="{safe_filename}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode()

        url = self.settings["romm_url"].rstrip("/") + path
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Authorization", self._romm_auth_header())
        try:
            with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
                return json.loads(resp.read().decode())
        except RommApiError:
            raise
        except Exception as exc:
            raise self._translate_http_error(exc, url, method) from exc
