"""RommClientMixin — thin delegation shim to RommHttpClient.

All HTTP logic lives in ``adapters.romm.client.RommHttpClient``.
This mixin exists only so that unmigrated mixins (SyncMixin,
etc.) can keep calling ``self._romm_request()``, ``self._with_retry()``, etc.
through the Plugin MRO without changes.

The lazy ``_http_client`` property auto-creates the client from
``self.settings`` on first access, so existing test fixtures (which set
``p.settings = {...}`` but never set ``_http_client``) keep working.
"""

from typing import TYPE_CHECKING

import decky
from adapters.romm.client import RommHttpClient

if TYPE_CHECKING:
    from typing import Protocol

    class _RommClientDeps(Protocol):
        settings: dict


class RommClientMixin(_RommClientDeps if TYPE_CHECKING else object):
    # -- lazy property: auto-creates client on first access ----------------

    @property
    def _http_client(self) -> RommHttpClient:
        if not hasattr(self, "_RommClientMixin__http_client"):
            self._RommClientMixin__http_client = RommHttpClient(self.settings, decky.DECKY_PLUGIN_DIR, decky.logger)
        return self._RommClientMixin__http_client

    @_http_client.setter
    def _http_client(self, value: RommHttpClient) -> None:
        self._RommClientMixin__http_client = value

    # -- delegation shims --------------------------------------------------

    def _load_platform_map(self):
        return self._http_client.load_platform_map()

    def _resolve_system(self, platform_slug, platform_fs_slug=None):
        return self._http_client.resolve_system(platform_slug, platform_fs_slug)

    def _romm_ssl_context(self):
        return self._http_client.ssl_context()

    def _romm_auth_header(self):
        return self._http_client.auth_header()

    def _translate_http_error(self, exc, url, method="GET"):
        return self._http_client.translate_http_error(exc, url, method)

    @staticmethod
    def _is_retryable(exc):
        return RommHttpClient.is_retryable(exc)

    def _with_retry(self, fn, *args, max_attempts=3, base_delay=1, **kwargs):
        return self._http_client.with_retry(fn, *args, max_attempts=max_attempts, base_delay=base_delay, **kwargs)

    def _romm_request(self, path):
        return self._http_client.request(path)

    def _romm_download(self, path, dest, progress_callback=None):
        return self._http_client.download(path, dest, progress_callback)

    def _romm_json_request(self, path, data, method="POST"):
        return self._http_client.json_request(path, data, method)

    def _romm_post_json(self, path, data):
        return self._http_client.post_json(path, data)

    def _romm_put_json(self, path, data):
        return self._http_client.put_json(path, data)

    def _romm_upload_multipart(self, path, file_path, method="POST"):
        return self._http_client.upload_multipart(path, file_path, method)
