import os
import json
import base64
import ssl
import uuid
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import TYPE_CHECKING

import decky

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
        config_path = os.path.join(decky.DECKY_PLUGIN_DIR, "defaults", "config.json")
        with open(config_path, "r") as f:
            config = json.load(f)
        return config.get("platform_map", {})

    def _resolve_system(self, platform_slug, platform_fs_slug=None):
        platform_map = self._load_platform_map()
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

    def _romm_request(self, path):
        url = self.settings["romm_url"].rstrip("/") + path
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", self._romm_auth_header())
        with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _romm_download(self, path, dest, progress_callback=None):
        encoded_path = urllib.parse.quote(path, safe="/:?=&@")
        url = self.settings["romm_url"].rstrip("/") + encoded_path
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", self._romm_auth_header())
        ctx = self._romm_ssl_context()
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
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

    def _romm_json_request(self, path, data, method="POST"):
        """Send a JSON request (POST/PUT) to RomM API, return parsed response."""
        url = self.settings["romm_url"].rstrip("/") + path
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", self._romm_auth_header())
        with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
            return json.loads(resp.read().decode())

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
        with urllib.request.urlopen(req, context=self._romm_ssl_context(), timeout=30) as resp:
            return json.loads(resp.read().decode())
