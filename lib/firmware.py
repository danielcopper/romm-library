import json
import os
import hashlib
import urllib.parse
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import decky

from lib import retrodeck_config

if TYPE_CHECKING:
    import asyncio
    from typing import Callable, Optional, Protocol

    class _FirmwareDeps(Protocol):
        _state: dict
        _bios_registry: dict
        loop: asyncio.AbstractEventLoop
        def _romm_request(self, path: str) -> Any: ...
        def _romm_download(self, path: str, dest: str, progress_callback: Optional[Callable] = None) -> None: ...
        def _save_state(self) -> None: ...


class FirmwareMixin:
    def _load_bios_registry(self):
        self._bios_registry = {}
        self._bios_files_index = {}
        registry_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "defaults", "bios_registry.json",
        )
        try:
            with open(registry_path, "r") as f:
                self._bios_registry = json.load(f)
            # Build flat reverse index: {filename: {entry_data + "platform": slug}}
            for platform, files in self._bios_registry.get("platforms", {}).items():
                for filename, entry in files.items():
                    self._bios_files_index[filename] = {**entry, "platform": platform}
        except FileNotFoundError:
            decky.logger.warning("bios_registry.json not found, registry enrichment disabled")
        except Exception as e:
            decky.logger.error(f"Failed to load bios_registry.json: {e}")

    def _enrich_firmware_file(self, file_dict):
        entry = self._bios_files_index.get(file_dict.get("file_name", ""))
        if entry:
            file_dict["required"] = entry.get("required", True)
            file_dict["description"] = entry.get("description", file_dict.get("file_name", ""))
            file_dict["classification"] = "required" if entry.get("required", True) else "optional"
        else:
            # Unknown file: not in registry, don't count as required
            file_dict["required"] = False
            file_dict["description"] = file_dict.get("file_name", "")
            file_dict["classification"] = "unknown"
        file_md5 = file_dict.get("md5", "")
        registry_md5 = entry.get("md5", "") if entry else ""
        if file_md5 and registry_md5:
            file_dict["hash_valid"] = file_md5.lower() == registry_md5.lower()
        else:
            file_dict["hash_valid"] = None
        return file_dict

    def _firmware_slug(self, file_path):
        """Extract firmware slug from file_path (e.g. 'bios/ps' -> 'ps')."""
        parts = file_path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "bios":
            return parts[1]
        elif len(parts) >= 2:
            return parts[0]
        return ""

    def _platform_to_firmware_slugs(self, platform_slug):
        """Map platform slug to possible firmware directory slugs.

        RomM uses different slugs for platforms vs firmware directories
        (e.g. platform 'psx' -> firmware dir 'ps').
        """
        mapping = {
            "psx": ["psx", "ps"],
            "ps2": ["ps2"],
        }
        return mapping.get(platform_slug, [platform_slug])

    def _firmware_dest_path(self, firmware):
        """Determine local destination path for a firmware file.

        Uses firmware_path from bios_registry.json for correct subdirectory
        placement (e.g. dc/dc_boot.bin). Falls back to flat in bios root
        for files not in the registry.
        """
        bios_base = retrodeck_config.get_bios_path()
        file_name = firmware.get("file_name", "")
        reg_entry = self._bios_files_index.get(file_name)
        if reg_entry and reg_entry.get("firmware_path"):
            return os.path.join(bios_base, reg_entry["firmware_path"])
        return os.path.join(bios_base, file_name)

    async def get_firmware_status(self):
        """Return BIOS/firmware status for all platforms on the RomM server."""
        try:
            firmware_list = await self.loop.run_in_executor(
                None, self._romm_request, "/api/firmware"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch firmware: {e}")
            return {"success": False, "message": f"Failed to fetch firmware: {e}", "platforms": []}

        # Group firmware by platform
        platforms_map = {}
        for fw in firmware_list:
            platform_slug = self._firmware_slug(fw.get("file_path", "")) or "unknown"

            if platform_slug not in platforms_map:
                platforms_map[platform_slug] = {
                    "platform_slug": platform_slug,
                    "files": [],
                }

            dest = self._firmware_dest_path(fw)
            file_dict = {
                "id": fw.get("id"),
                "file_name": fw.get("file_name", ""),
                "size": fw.get("file_size_bytes", 0),
                "md5": fw.get("md5_hash", ""),
                "downloaded": os.path.exists(dest),
            }
            self._enrich_firmware_file(file_dict)
            platforms_map[platform_slug]["files"].append(file_dict)

        # Cross-reference: installed platforms that have firmware on server but not all downloaded
        installed_slugs = set()
        for entry in self._state["shortcut_registry"].values():
            slug = entry.get("platform_slug", "")
            if slug:
                installed_slugs.add(slug)

        # Mark platforms where user has games installed
        for plat in platforms_map.values():
            plat["has_games"] = plat["platform_slug"] in installed_slugs
            plat["all_downloaded"] = all(f["downloaded"] for f in plat["files"])

        platforms = sorted(platforms_map.values(), key=lambda p: p["platform_slug"])
        return {"success": True, "platforms": platforms}

    async def download_firmware(self, firmware_id):
        """Download a single firmware file from RomM."""
        firmware_id = int(firmware_id)
        try:
            fw = await self.loop.run_in_executor(
                None, self._romm_request, f"/api/firmware/{firmware_id}"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch firmware {firmware_id}: {e}")
            return {"success": False, "message": f"Failed to fetch firmware details: {e}"}

        file_name = fw.get("file_name", "")
        dest = self._firmware_dest_path(fw)
        tmp_path = dest + ".tmp"

        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            download_path = f"/api/firmware/{firmware_id}/content/{urllib.parse.quote(file_name, safe='')}"
            await self.loop.run_in_executor(
                None, self._romm_download, download_path, tmp_path
            )
            os.replace(tmp_path, dest)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            decky.logger.error(f"Failed to download firmware {file_name}: {e}")
            return {"success": False, "message": f"Download failed: {e}"}

        # Verify MD5 if available
        md5_match = None
        expected_md5 = fw.get("md5_hash", "")
        local_md5 = None
        if expected_md5:
            h = hashlib.md5()
            with open(dest, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            local_md5 = h.hexdigest()
            md5_match = local_md5 == expected_md5

        # Check against registry hash
        registry_hash_valid = None
        reg_entry = self._bios_files_index.get(file_name)
        if reg_entry:
            reg_md5 = reg_entry.get("md5", "")
            if reg_md5:
                if local_md5 is None:
                    h = hashlib.md5()
                    with open(dest, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            h.update(chunk)
                    local_md5 = h.hexdigest()
                registry_hash_valid = local_md5.lower() == reg_md5.lower()

        # Track in state for migration support
        self._state["downloaded_bios"][file_name] = {
            "file_path": dest,
            "firmware_id": firmware_id,
            "platform_slug": self._firmware_slug(fw.get("file_path", "")),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_state()

        decky.logger.info(f"Firmware downloaded: {file_name} -> {dest}")
        return {"success": True, "file_path": dest, "md5_match": md5_match, "registry_hash_valid": registry_hash_valid}

    async def download_all_firmware(self, platform_slug):
        """Download all firmware for a given platform slug."""
        try:
            firmware_list = await self.loop.run_in_executor(
                None, self._romm_request, "/api/firmware"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch firmware: {e}")
            return {"success": False, "message": f"Failed to fetch firmware: {e}", "downloaded": 0}

        # Filter by platform slug (use mapped slugs, e.g. "psx" -> ["psx", "ps"])
        fw_slugs = self._platform_to_firmware_slugs(platform_slug)
        platform_firmware = []
        for fw in firmware_list:
            slug = self._firmware_slug(fw.get("file_path", ""))
            if slug in fw_slugs:
                platform_firmware.append(fw)

        downloaded = 0
        errors = []
        for fw in platform_firmware:
            dest = self._firmware_dest_path(fw)
            if os.path.exists(dest):
                continue
            result = await self.download_firmware(fw["id"])
            if result.get("success"):
                downloaded += 1
            else:
                errors.append(fw.get("file_name", str(fw["id"])))

        msg = f"Downloaded {downloaded} firmware files"
        if errors:
            msg += f" ({len(errors)} failed: {', '.join(errors)})"
        return {"success": True, "message": msg, "downloaded": downloaded}

    async def download_required_firmware(self, platform_slug):
        """Download only required firmware for a given platform slug."""
        try:
            firmware_list = await self.loop.run_in_executor(
                None, self._romm_request, "/api/firmware"
            )
        except Exception as e:
            decky.logger.error(f"Failed to fetch firmware: {e}")
            return {"success": False, "message": f"Failed to fetch firmware: {e}", "downloaded": 0}

        fw_slugs = self._platform_to_firmware_slugs(platform_slug)
        platform_firmware = []
        for fw in firmware_list:
            slug = self._firmware_slug(fw.get("file_path", ""))
            if slug in fw_slugs:
                file_name = fw.get("file_name", "")
                index_entry = self._bios_files_index.get(file_name)
                # Only download files that are in the index with required=True
                # Unknown files (not in index) are NOT downloaded
                if index_entry and index_entry.get("required", True):
                    platform_firmware.append(fw)

        downloaded = 0
        errors = []
        for fw in platform_firmware:
            dest = self._firmware_dest_path(fw)
            if os.path.exists(dest):
                continue
            result = await self.download_firmware(fw["id"])
            if result.get("success"):
                downloaded += 1
            else:
                errors.append(fw.get("file_name", str(fw["id"])))

        msg = f"Downloaded {downloaded} required firmware files"
        if errors:
            msg += f" ({len(errors)} failed: {', '.join(errors)})"
        return {"success": True, "message": msg, "downloaded": downloaded}

    async def check_platform_bios(self, platform_slug):
        """Check if RomM has firmware for this platform and whether it's downloaded."""
        local_count = 0
        server_count = 0
        files = []
        fw_slugs = self._platform_to_firmware_slugs(platform_slug)

        # Build combined registry entries for this platform from all mapped slugs
        registry_platform = {}
        for slug in fw_slugs:
            registry_platform.update(self._bios_registry.get("platforms", {}).get(slug, {}))

        try:
            firmware_list = await self.loop.run_in_executor(
                None, self._romm_request, "/api/firmware"
            )
            for fw in firmware_list:
                fw_slug = self._firmware_slug(fw.get("file_path", ""))
                if not fw_slug:
                    continue
                if fw_slug in fw_slugs:
                    server_count += 1
                    dest = self._firmware_dest_path(fw)
                    downloaded = os.path.exists(dest)
                    if downloaded:
                        local_count += 1
                    file_name = fw.get("file_name", "")
                    reg_entry = registry_platform.get(file_name)
                    if reg_entry:
                        classification = "required" if reg_entry.get("required", True) else "optional"
                        is_required = reg_entry.get("required", True)
                        description = reg_entry.get("description", file_name)
                    else:
                        classification = "unknown"
                        is_required = False
                        description = file_name
                    files.append({
                        "file_name": file_name,
                        "downloaded": downloaded,
                        "local_path": dest,
                        "required": is_required,
                        "description": description,
                        "classification": classification,
                    })
        except Exception:
            pass

        if server_count == 0:
            return {"needs_bios": False}

        required_files = [f for f in files if f["classification"] == "required"]
        required_count = len(required_files)
        required_downloaded = sum(1 for f in required_files if f["downloaded"])
        unknown_count = sum(1 for f in files if f["classification"] == "unknown")

        return {
            "needs_bios": True,
            "server_count": server_count,
            "local_count": local_count,
            "all_downloaded": local_count >= server_count,
            "required_count": required_count,
            "required_downloaded": required_downloaded,
            "unknown_count": unknown_count,
            "files": files,
        }

    async def delete_platform_bios(self, platform_slug):
        """Delete locally downloaded BIOS files for a platform."""
        bios_status = await self.check_platform_bios(platform_slug)
        if not bios_status.get("needs_bios") or not bios_status.get("files"):
            return {"success": True, "deleted_count": 0, "message": "No BIOS files for this platform"}

        deleted = 0
        errors = []
        for f in bios_status["files"]:
            if not f.get("downloaded"):
                continue
            try:
                os.remove(f["local_path"])
                deleted += 1
                # Remove from state tracking
                self._state["downloaded_bios"].pop(f["file_name"], None)
            except Exception as e:
                errors.append(f"{f['file_name']}: {e}")

        if deleted:
            self._save_state()

        if errors:
            return {"success": False, "deleted_count": deleted, "message": f"Deleted {deleted} file(s), {len(errors)} error(s)"}
        return {"success": True, "deleted_count": deleted, "message": f"Deleted {deleted} BIOS file(s)"}
