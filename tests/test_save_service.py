"""Tests for SaveService with FakeSaveApi (no HTTP, no mocking)."""

import asyncio
import hashlib
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fakes.fake_save_api import FakeSaveApi

from lib.errors import RommApiError
from services.saves import SaveService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_retry(fn, *a, **kw):
    return fn(*a, **kw)


def _make_retry():
    retry = MagicMock()
    retry.with_retry.side_effect = _no_retry
    retry.is_retryable.return_value = False
    return retry


def make_service(tmp_path, fake_api=None, **overrides) -> tuple["SaveService", "FakeSaveApi"]:
    """Create a SaveService with sensible defaults for testing."""
    fake: FakeSaveApi = fake_api or FakeSaveApi()
    defaults: dict[str, Any] = dict(
        romm_api=fake,
        retry=_make_retry(),
        state={"shortcut_registry": {}, "installed_roms": {}},
        save_sync_state=SaveService.make_default_state(),
        loop=asyncio.get_event_loop(),
        logger=logging.getLogger("test"),
        runtime_dir=str(tmp_path),
        get_saves_path=lambda: str(tmp_path / "saves"),
    )
    defaults.update(overrides)
    svc = SaveService(**defaults)
    svc.init_state()
    return svc, fake


def _install_rom(svc, tmp_path, rom_id=42, system="gba", file_name="pokemon.gba"):
    """Register a ROM in installed_roms state."""
    svc._state["installed_roms"][str(rom_id)] = {
        "rom_id": rom_id,
        "file_name": file_name,
        "file_path": str(tmp_path / "retrodeck" / "roms" / system / file_name),
        "system": system,
        "platform_slug": system,
        "installed_at": "2026-01-01T00:00:00",
    }


def _create_save(tmp_path, system="gba", rom_name="pokemon", content=b"\x00" * 1024, ext=".srm"):
    """Create a save file on disk and return its path."""
    saves_dir = tmp_path / "saves" / system
    saves_dir.mkdir(parents=True, exist_ok=True)
    save_file = saves_dir / (rom_name + ext)
    save_file.write_bytes(content)
    return save_file


def _server_save(
    save_id=100, rom_id=42, filename="pokemon.srm", updated_at="2026-02-17T06:00:00Z", file_size_bytes=1024
):
    return {
        "id": save_id,
        "rom_id": rom_id,
        "file_name": filename,
        "updated_at": updated_at,
        "file_size_bytes": file_size_bytes,
        "emulator": "retroarch",
        "download_path": f"/saves/{filename}",
    }


def _file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# TestStateManagement
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_make_default_state(self):
        state = SaveService.make_default_state()
        assert state["device_id"] is None
        assert state["saves"] == {}
        assert state["settings"]["save_sync_enabled"] is False

    def test_init_state_populates_defaults(self, tmp_path):
        svc, _ = make_service(tmp_path, save_sync_state={})
        assert svc._save_sync_state["settings"]["conflict_mode"] == "ask_me"
        assert svc._save_sync_state["saves"] == {}

    def test_init_state_preserves_existing(self, tmp_path):
        state = SaveService.make_default_state()
        state["device_id"] = "existing-id"
        svc, _ = make_service(tmp_path, save_sync_state=state)
        assert svc._save_sync_state["device_id"] == "existing-id"

    def test_save_and_load_state(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["device_id"] = "test-device"
        svc._save_sync_state["saves"]["42"] = {"files": {}}
        svc.save_state()

        # Load into a fresh service
        svc2, _ = make_service(tmp_path)
        svc2.load_state()
        assert svc2._save_sync_state["device_id"] == "test-device"
        assert "42" in svc2._save_sync_state["saves"]

    def test_load_state_missing_file(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.load_state()  # should not raise
        assert svc._save_sync_state["device_id"] is None

    def test_prune_orphaned_state(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["saves"]["99"] = {"files": {}}
        svc._save_sync_state["playtime"]["99"] = {"total_seconds": 100}
        svc._state["shortcut_registry"]["42"] = {}

        svc.prune_orphaned_state()
        assert "99" not in svc._save_sync_state["saves"]
        assert "99" not in svc._save_sync_state["playtime"]

    def test_prune_keeps_registered(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["saves"]["42"] = {"files": {}}
        svc._state["shortcut_registry"]["42"] = {}

        svc.prune_orphaned_state()
        assert "42" in svc._save_sync_state["saves"]


# ---------------------------------------------------------------------------
# TestDeviceRegistration
# ---------------------------------------------------------------------------


class TestDeviceRegistration:
    @pytest.mark.asyncio
    async def test_registers_new_device(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True

        result = svc.ensure_device_registered()
        assert result["success"] is True
        assert result["device_id"]
        assert result["device_name"]
        # Persisted
        assert svc._save_sync_state["device_id"] == result["device_id"]

    @pytest.mark.asyncio
    async def test_returns_existing_device(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "existing"
        svc._save_sync_state["device_name"] = "deck"

        result = svc.ensure_device_registered()
        assert result["device_id"] == "existing"
        assert result["device_name"] == "deck"

    @pytest.mark.asyncio
    async def test_disabled_returns_failure(self, tmp_path):
        svc, _ = make_service(tmp_path)
        # save_sync_enabled defaults to False
        result = svc.ensure_device_registered()
        assert result["success"] is False
        assert result.get("disabled") is True


# ---------------------------------------------------------------------------
# TestConflictDetection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def test_skip_when_unchanged(self, tmp_path):
        svc, _ = make_service(tmp_path)
        content = b"save data"
        local_hash = hashlib.md5(content).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"

    def test_upload_when_local_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        old_hash = hashlib.md5(b"old").hexdigest()
        new_hash = hashlib.md5(b"new data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": old_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", new_hash, server)
        assert result == "upload"

    def test_download_when_server_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        local_hash = hashlib.md5(b"save data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        # Server has a different updated_at, and downloading it yields a different hash
        server = _server_save(updated_at="2026-02-17T08:00:00Z", file_size_bytes=2048)
        # The slow path will download + hash. The fake will write default content.
        # We need the downloaded hash to differ from last_sync_hash.
        # Since FakeSaveApi.download_save writes 1024 zero bytes and local_hash is md5("save data"),
        # the server hash will naturally differ.
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "download"

    def test_conflict_when_both_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        old_hash = hashlib.md5(b"baseline").hexdigest()
        new_local = hashlib.md5(b"local edit").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": old_hash,
                    "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T08:00:00Z", file_size_bytes=2048)
        result = svc._detect_conflict(42, "pokemon.srm", new_local, server)
        assert result == "conflict"

    def test_never_synced_same_hash_skips(self, tmp_path):
        """When never synced but local and server have same content -> skip."""
        svc, _ = make_service(tmp_path)
        # FakeSaveApi.download_save writes 1024 zero bytes
        content = b"\x00" * 1024
        local_hash = hashlib.md5(content).hexdigest()

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"

    def test_never_synced_different_hash_conflicts(self, tmp_path):
        """When never synced and hashes differ -> conflict."""
        svc, _ = make_service(tmp_path)
        local_hash = hashlib.md5(b"different content").hexdigest()

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "conflict"

    def test_first_sync_download_fails(self, tmp_path):
        """First sync (no snapshot), server download fails -> conflict."""
        svc, fake = make_service(tmp_path)
        local_hash = hashlib.md5(b"local data").hexdigest()

        server = _server_save()
        fake.fail_on_next(Exception("download failed"))
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "conflict"

    def test_no_local_file_downloads(self, tmp_path):
        """No local file (local_hash=None), server has save -> download."""
        svc, _ = make_service(tmp_path)

        server = _server_save()
        result = svc._detect_conflict(42, "pokemon.srm", None, server)
        assert result == "download"

    def test_server_size_change_fast_path(self, tmp_path):
        """Same timestamp but different size -> detects server changed."""
        svc, _ = make_service(tmp_path)
        local_hash = hashlib.md5(b"save data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        # Same timestamp but different size -> fast path detects change
        server = _server_save(updated_at="2026-02-17T06:00:00Z", file_size_bytes=2048)
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        # local unchanged, server changed -> download
        assert result == "download"


# ---------------------------------------------------------------------------
# TestConflictDetectionFalseAlarm
# ---------------------------------------------------------------------------


class TestConflictDetectionFalseAlarm:
    """Timestamp changed but content identical -> false alarm detection."""

    def test_timestamp_changed_content_identical_skips(self, tmp_path):
        """Server timestamp changed but content hash matches baseline -> skip."""
        svc, _ = make_service(tmp_path)
        # FakeSaveApi.download_save writes 1024 zero bytes by default
        baseline_hash = hashlib.md5(b"\x00" * 1024).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        # Different timestamp triggers slow path; download yields same hash as baseline
        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        result = svc._detect_conflict(42, "pokemon.srm", baseline_hash, server)
        assert result == "skip"

    def test_false_alarm_updates_stored_metadata(self, tmp_path):
        """After false alarm, stored server_updated_at and server_size are updated."""
        svc, _ = make_service(tmp_path)
        baseline_hash = hashlib.md5(b"\x00" * 1024).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T12:00:00Z", file_size_bytes=2048)
        svc._detect_conflict(42, "pokemon.srm", baseline_hash, server)

        file_state = svc._save_sync_state["saves"]["42"]["files"]["pokemon.srm"]
        assert file_state["last_sync_server_updated_at"] == "2026-02-17T12:00:00Z"
        assert file_state["last_sync_server_size"] == 2048

    def test_local_changed_server_content_unchanged_uploads(self, tmp_path):
        """Local changed + server timestamp changed but server content unchanged -> upload."""
        svc, _ = make_service(tmp_path)
        baseline_hash = hashlib.md5(b"\x00" * 1024).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        new_local_hash = hashlib.md5(b"new local data").hexdigest()
        result = svc._detect_conflict(42, "pokemon.srm", new_local_hash, server)
        assert result == "upload"

    def test_no_stored_timestamp_triggers_slow_path(self, tmp_path):
        """No stored server_updated_at -> triggers slow path (download + hash)."""
        svc, _ = make_service(tmp_path)
        baseline_hash = hashlib.md5(b"\x00" * 1024).hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    # No last_sync_server_updated_at
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        # Slow path downloads save, hash matches baseline -> skip
        result = svc._detect_conflict(42, "pokemon.srm", baseline_hash, server)
        assert result == "skip"

    def test_slow_path_download_fails_server_unchanged(self, tmp_path):
        """_get_server_save_hash returns None (download failed) -> treated as server unchanged."""
        svc, fake = make_service(tmp_path)
        baseline_hash = hashlib.md5(b"baseline").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        fake.fail_on_next(Exception("download failed"))
        # Local unchanged + server hash None -> server unchanged -> skip
        result = svc._detect_conflict(42, "pokemon.srm", baseline_hash, server)
        assert result == "skip"

    def test_slow_path_download_fails_local_changed(self, tmp_path):
        """_get_server_save_hash returns None, local changed -> upload."""
        svc, fake = make_service(tmp_path)
        baseline_hash = hashlib.md5(b"baseline").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": baseline_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        fake.fail_on_next(Exception("download failed"))
        new_local_hash = hashlib.md5(b"new local data").hexdigest()
        result = svc._detect_conflict(42, "pokemon.srm", new_local_hash, server)
        assert result == "upload"

    def test_fast_path_timestamp_and_size_match(self, tmp_path):
        """Both timestamp and size match stored -> skip."""
        svc, _ = make_service(tmp_path)
        local_hash = hashlib.md5(b"save data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": 1024,
                }
            }
        }

        server = _server_save(updated_at="2026-02-17T06:00:00Z", file_size_bytes=1024)
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"

    def test_fast_path_stored_size_none(self, tmp_path):
        """stored_size is None (legacy), timestamp matches -> skip (size check skipped)."""
        svc, _ = make_service(tmp_path)
        local_hash = hashlib.md5(b"save data").hexdigest()

        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
                    "last_sync_server_size": None,
                }
            }
        }

        # Different file size but stored_size is None -> size check skipped -> unchanged
        server = _server_save(updated_at="2026-02-17T06:00:00Z", file_size_bytes=2048)
        result = svc._detect_conflict(42, "pokemon.srm", local_hash, server)
        assert result == "skip"


# ---------------------------------------------------------------------------
# TestConflictDetectionLightweight
# ---------------------------------------------------------------------------


class TestConflictDetectionLightweight:
    def test_skip_when_unchanged(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save()
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, file_state)
        assert result == "skip"

    def test_upload_local_only(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {"last_sync_hash": "abc", "last_sync_local_mtime": 1000.0}
        result = svc._detect_conflict_lightweight(2000.0, 1024, None, file_state)
        assert result == "upload"

    def test_download_server_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save(updated_at="2026-02-17T08:00:00Z")
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, file_state)
        assert result == "download"

    def test_conflict_both_changed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = _server_save(updated_at="2026-02-17T08:00:00Z")
        result = svc._detect_conflict_lightweight(2000.0, 1024, server, file_state)
        assert result == "conflict"

    def test_never_synced_no_server(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = svc._detect_conflict_lightweight(1000.0, 1024, None, {})
        assert result == "upload"

    def test_never_synced_with_server(self, tmp_path):
        svc, _ = make_service(tmp_path)
        server = _server_save()
        result = svc._detect_conflict_lightweight(1000.0, 1024, server, {})
        assert result == "conflict"


# ---------------------------------------------------------------------------
# TestSyncRomSaves
# ---------------------------------------------------------------------------


class TestSyncRomSaves:
    def test_local_only_uploads(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"save data")

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 1
        assert errors == []
        assert conflicts == []
        assert any(c[0] == "upload_save" for c in fake.call_log)

    def test_server_only_downloads(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        # Add server save but no local file
        ss = _server_save()
        fake.saves[100] = ss

        synced, errors, _ = svc._sync_rom_saves(42)
        assert synced == 1
        assert errors == []
        # Verify the file was downloaded
        saves_dir = tmp_path / "saves" / "gba"
        assert (saves_dir / "pokemon.srm").exists()

    def test_matching_saves_skip(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)
        local_hash = _file_md5(str(save_path))

        ss = _server_save()
        fake.saves[100] = ss

        # Set sync state to match
        svc._save_sync_state["saves"]["42"] = {
            "files": {
                "pokemon.srm": {
                    "last_sync_hash": local_hash,
                    "last_sync_server_updated_at": ss["updated_at"],
                    "last_sync_server_size": ss["file_size_bytes"],
                }
            }
        }

        synced, errors, conflicts = svc._sync_rom_saves(42)
        assert synced == 0
        assert errors == []
        assert conflicts == []

    def test_rom_not_installed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        synced, errors, _ = svc._sync_rom_saves(999)
        assert synced == 0
        assert errors == []

    def test_api_error_on_list_saves(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        fake.fail_on_next(RommApiError("Server error"))

        synced, errors, _ = svc._sync_rom_saves(42)
        assert synced == 0
        assert len(errors) == 1
        assert "Failed to fetch saves" in errors[0]


# ---------------------------------------------------------------------------
# TestSyncAllSaves
# ---------------------------------------------------------------------------


class TestSyncAllSaves:
    @pytest.mark.asyncio
    async def test_syncs_multiple_roms(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"

        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1", content=b"save1")
        _create_save(tmp_path, system="snes", rom_name="game2", content=b"save2")

        result = await svc.sync_all_saves()
        assert result["success"] is True
        assert result["synced"] == 2
        assert result["roms_checked"] == 2

    @pytest.mark.asyncio
    async def test_disabled_returns_early(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.sync_all_saves()
        assert result["success"] is False
        assert "disabled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_partial_failure(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"

        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1", content=b"save1")
        _create_save(tmp_path, system="snes", rom_name="game2", content=b"save2")

        # Make the second ROM's list_saves fail
        original_list = fake.list_saves

        call_count = 0

        def flaky_list(rom_id, *, device_id=None, slot=None):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RommApiError("Server error")
            return original_list(rom_id, device_id=device_id, slot=slot)

        fake.list_saves = flaky_list

        result = await svc.sync_all_saves()
        assert result["synced"] >= 1
        assert len(result["errors"]) >= 1


# ---------------------------------------------------------------------------
# TestPreLaunchSync
# ---------------------------------------------------------------------------


class TestPreLaunchSync:
    @pytest.mark.asyncio
    async def test_downloads_server_saves(self, tmp_path):
        svc, fake = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"
        _install_rom(svc, tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.pre_launch_sync(42)
        assert result["success"] is True
        assert result["synced"] == 1

    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.pre_launch_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_pre_launch_disabled_in_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["settings"]["sync_before_launch"] = False
        svc._save_sync_state["device_id"] = "test-device"

        result = await svc.pre_launch_sync(42)
        assert result["synced"] == 0


# ---------------------------------------------------------------------------
# TestPostExitSync
# ---------------------------------------------------------------------------


class TestPostExitSync:
    @pytest.mark.asyncio
    async def test_uploads_changed_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"new save data")

        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert result["synced"] == 1

    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_post_exit_disabled_in_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["settings"]["sync_after_exit"] = False
        svc._save_sync_state["device_id"] = "test-device"

        result = await svc.post_exit_sync(42)
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_auto_registers_device(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        # No device_id set
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"data")

        result = await svc.post_exit_sync(42)
        assert result["success"] is True
        assert svc._save_sync_state["device_id"] is not None


# ---------------------------------------------------------------------------
# TestPostExitSyncConnectivity
# ---------------------------------------------------------------------------


class TestPostExitSyncConnectivity:
    @pytest.mark.asyncio
    async def test_returns_offline_when_heartbeat_fails(self, tmp_path):
        """post_exit_sync returns offline=True when server is unreachable."""
        fake = FakeSaveApi()
        fake.heartbeat_raises = ConnectionError("unreachable")
        svc, _ = make_service(tmp_path, fake_api=fake)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"

        result = await svc.post_exit_sync(42)

        assert result["success"] is False
        assert result.get("offline") is True
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_proceeds_when_heartbeat_succeeds(self, tmp_path):
        """post_exit_sync proceeds normally when server is reachable."""
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        svc._save_sync_state["device_id"] = "test-device"
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"save data")

        result = await svc.post_exit_sync(42)

        assert result.get("offline") is not True
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_offline_skips_before_device_registration(self, tmp_path):
        """post_exit_sync returns offline without attempting device registration."""
        fake = FakeSaveApi()
        fake.heartbeat_raises = OSError("connection refused")
        svc, _ = make_service(tmp_path, fake_api=fake)
        svc._save_sync_state["settings"]["save_sync_enabled"] = True
        # No device_id — would trigger registration if heartbeat passed

        result = await svc.post_exit_sync(42)

        assert result.get("offline") is True
        # Device should not have been registered
        assert not svc._save_sync_state.get("device_id")


# ---------------------------------------------------------------------------
# TestResolveConflict
# ---------------------------------------------------------------------------


class TestResolveConflict:
    @pytest.mark.asyncio
    async def test_download_resolution(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.resolve_conflict(
            rom_id=42,
            filename="pokemon.srm",
            resolution="download",
            server_save_id=100,
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_upload_resolution(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.resolve_conflict(
            rom_id=42,
            filename="pokemon.srm",
            resolution="upload",
            server_save_id=100,
            local_path=str(save_path),
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_resolution(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=42, filename="x.srm", resolution="invalid", server_save_id=100)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_missing_server_save_id(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=42, filename="x.srm", resolution="download")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_rom_not_installed(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = await svc.resolve_conflict(rom_id=999, filename="x.srm", resolution="download", server_save_id=100)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# TestSaveStatus
# ---------------------------------------------------------------------------


class TestSaveStatus:
    @pytest.mark.asyncio
    async def test_get_save_status(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.get_save_status(42)
        assert result["rom_id"] == 42
        assert len(result["files"]) >= 1

    @pytest.mark.asyncio
    async def test_get_save_status_no_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = await svc.get_save_status(42)
        assert result["rom_id"] == 42
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_check_save_status_lightweight(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path)

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.check_save_status_lightweight(42)
        assert result["rom_id"] == 42
        assert len(result["files"]) >= 1
        # Lightweight should not hash
        for f in result["files"]:
            assert f["local_hash"] is None

    @pytest.mark.asyncio
    async def test_get_save_status_includes_empty_conflicts_when_no_conflict(self, tmp_path):
        """get_save_status response includes conflicts key (empty when no conflicts)."""
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = await svc.get_save_status(42)
        assert "conflicts" in result
        assert result["conflicts"] == []

    @pytest.mark.asyncio
    async def test_get_save_status_conflicts_populated_when_conflict_detected(self, tmp_path):
        """When local and server both exist but never synced, conflicts list is populated."""
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        # Create local file with content different from server (server writes zeros)
        _create_save(tmp_path, content=b"different content")

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.get_save_status(42)
        assert "conflicts" in result
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["filename"] == "pokemon.srm"
        assert result["conflicts"][0]["rom_id"] == 42

    @pytest.mark.asyncio
    async def test_get_save_status_conflicts_has_required_fields(self, tmp_path):
        """Conflict entries include all fields needed for resolution."""
        svc, fake = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, content=b"different content")

        ss = _server_save()
        fake.saves[100] = ss

        result = await svc.get_save_status(42)
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["rom_id"] == 42
        assert conflict["filename"] == "pokemon.srm"
        assert conflict["local_path"] is not None
        assert conflict["server_save_id"] == 100
        assert conflict["server_updated_at"] == "2026-02-17T06:00:00Z"
        assert "created_at" in conflict


# ---------------------------------------------------------------------------
# TestSettings
# ---------------------------------------------------------------------------


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_defaults(self, tmp_path):
        svc, _ = make_service(tmp_path)
        settings = svc.get_save_sync_settings()
        assert settings["conflict_mode"] == "ask_me"
        assert settings["save_sync_enabled"] is False

    @pytest.mark.asyncio
    async def test_update_settings(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = svc.update_save_sync_settings(
            {
                "save_sync_enabled": True,
                "conflict_mode": "newest_wins",
            }
        )
        assert result["success"] is True
        assert result["settings"]["save_sync_enabled"] is True
        assert result["settings"]["conflict_mode"] == "newest_wins"

    @pytest.mark.asyncio
    async def test_invalid_mode_ignored(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.update_save_sync_settings({"conflict_mode": "invalid_mode"})
        settings = svc.get_save_sync_settings()
        assert settings["conflict_mode"] == "ask_me"

    @pytest.mark.asyncio
    async def test_unknown_key_ignored(self, tmp_path):
        svc, _ = make_service(tmp_path)
        result = svc.update_save_sync_settings({"unknown_key": "value"})
        assert result["success"] is True
        assert "unknown_key" not in result["settings"]

    @pytest.mark.asyncio
    async def test_clock_skew_clamped(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc.update_save_sync_settings({"clock_skew_tolerance_sec": -10})
        settings = svc.get_save_sync_settings()
        assert settings["clock_skew_tolerance_sec"] == 0


# ---------------------------------------------------------------------------
# TestDeleteSaves
# ---------------------------------------------------------------------------


class TestDeleteSaves:
    @pytest.mark.asyncio
    async def test_delete_local_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        save_path = _create_save(tmp_path)
        assert save_path.exists()

        svc._save_sync_state["saves"]["42"] = {"files": {"pokemon.srm": {}}}

        result = svc.delete_local_saves(42)
        assert result["success"] is True
        assert result["deleted_count"] == 1
        assert not save_path.exists()
        assert "42" not in svc._save_sync_state["saves"]

    @pytest.mark.asyncio
    async def test_delete_no_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = svc.delete_local_saves(42)
        assert result["success"] is True
        assert result["deleted_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_platform_saves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="gba", file_name="game2.gba")
        _create_save(tmp_path, system="gba", rom_name="game1")
        _create_save(tmp_path, system="gba", rom_name="game2")

        result = svc.delete_platform_saves("gba")
        assert result["success"] is True
        assert result["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_delete_platform_saves_other_platform_untouched(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=1, system="gba", file_name="game1.gba")
        _install_rom(svc, tmp_path, rom_id=2, system="snes", file_name="game2.sfc")
        _create_save(tmp_path, system="gba", rom_name="game1")
        snes_save = _create_save(tmp_path, system="snes", rom_name="game2")

        svc.delete_platform_saves("gba")
        assert snes_save.exists()


# ---------------------------------------------------------------------------
# TestFindSaveFiles
# ---------------------------------------------------------------------------


class TestFindSaveFiles:
    """Tests for _find_save_files."""

    def test_finds_srm(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)
        _create_save(tmp_path, system="gba", rom_name="pokemon")

        result = svc._find_save_files(42)

        assert len(result) == 1
        assert result[0]["filename"] == "pokemon.srm"
        assert result[0]["path"].endswith("pokemon.srm")

    def test_finds_rtc_companion(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, file_name="emerald.gba")
        _create_save(tmp_path, system="gba", rom_name="emerald", ext=".srm")
        _create_save(tmp_path, system="gba", rom_name="emerald", ext=".rtc", content=b"\x02" * 16)

        result = svc._find_save_files(42)

        filenames = sorted(f["filename"] for f in result)
        assert filenames == ["emerald.rtc", "emerald.srm"]

    def test_multi_disc_uses_m3u_name(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._state["installed_roms"]["55"] = {
            "rom_id": 55,
            "file_name": "FF7.zip",
            "file_path": str(tmp_path / "retrodeck" / "roms" / "psx" / "FF7" / "Final Fantasy VII.m3u"),
            "system": "psx",
            "platform_slug": "psx",
            "rom_dir": str(tmp_path / "retrodeck" / "roms" / "psx" / "FF7"),
            "installed_at": "2026-01-01T00:00:00",
        }
        _create_save(tmp_path, system="psx", rom_name="Final Fantasy VII")

        result = svc._find_save_files(55)

        assert any(f["filename"] == "Final Fantasy VII.srm" for f in result)

    def test_no_save_file_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path, rom_id=10, system="n64", file_name="zelda.z64")
        (tmp_path / "saves" / "n64").mkdir(parents=True, exist_ok=True)

        result = svc._find_save_files(10)

        assert result == []

    def test_saves_dir_not_exists_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = svc._find_save_files(42)

        assert result == []

    def test_rom_not_installed_returns_empty(self, tmp_path):
        svc, _ = make_service(tmp_path)

        result = svc._find_save_files(999)

        assert result == []


# ---------------------------------------------------------------------------
# TestFileMd5
# ---------------------------------------------------------------------------


class TestFileMd5:
    """Tests for _file_md5."""

    def test_known_content(self, tmp_path):
        f = tmp_path / "test.srm"
        content = b"Hello, save file!"
        f.write_bytes(content)

        assert SaveService._file_md5(str(f)) == hashlib.md5(content).hexdigest()

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.srm"
        f.write_bytes(b"")

        assert SaveService._file_md5(str(f)) == hashlib.md5(b"").hexdigest()

    def test_large_file_chunked(self, tmp_path):
        f = tmp_path / "large.srm"
        content = os.urandom(2 * 1024 * 1024)
        f.write_bytes(content)

        assert SaveService._file_md5(str(f)) == hashlib.md5(content).hexdigest()

    def test_permission_error(self, tmp_path):
        f = tmp_path / "locked.srm"
        f.write_bytes(b"data")
        f.chmod(0o000)

        try:
            with pytest.raises(PermissionError):
                SaveService._file_md5(str(f))
        finally:
            f.chmod(0o644)


# ---------------------------------------------------------------------------
# TestResolveConflictByMode
# ---------------------------------------------------------------------------


class TestResolveConflictByMode:
    """Tests for _resolve_conflict_by_mode."""

    def test_always_upload(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "always_upload"
        server = _server_save(updated_at="2026-02-17T12:00:00Z")

        result = svc._resolve_conflict_by_mode(time.time() - 7200, server)

        assert result == "upload"

    def test_always_download(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "always_download"
        server = _server_save(updated_at="2026-02-17T10:00:00Z")

        result = svc._resolve_conflict_by_mode(time.time(), server)

        assert result == "download"

    def test_ask_me(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "ask_me"
        server = _server_save()

        result = svc._resolve_conflict_by_mode(time.time(), server)

        assert result == "ask"

    def test_newest_wins_local_newer(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        server = _server_save(updated_at="2026-02-17T10:00:00Z")
        local_mtime = datetime(2026, 2, 17, 14, 0, 0, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "upload"

    def test_newest_wins_server_newer(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        server = _server_save(updated_at="2026-02-17T14:00:00Z")
        local_mtime = datetime(2026, 2, 17, 10, 0, 0, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "download"

    def test_newest_wins_within_clock_skew(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        svc._save_sync_state["settings"]["clock_skew_tolerance_sec"] = 60
        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        local_mtime = datetime(2026, 2, 17, 12, 0, 30, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "ask"


# ---------------------------------------------------------------------------
# TestClockSkewBoundary
# ---------------------------------------------------------------------------


class TestClockSkewBoundary:
    """Boundary tests for clock skew tolerance in newest_wins mode."""

    def test_exactly_at_tolerance_boundary_asks(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        svc._save_sync_state["settings"]["clock_skew_tolerance_sec"] = 60

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        local_mtime = datetime(2026, 2, 17, 12, 1, 0, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "ask"

    def test_one_second_beyond_tolerance_resolves(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        svc._save_sync_state["settings"]["clock_skew_tolerance_sec"] = 60

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        local_mtime = datetime(2026, 2, 17, 12, 1, 1, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "upload"

    def test_zero_tolerance_resolves_any_difference(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"
        svc._save_sync_state["settings"]["clock_skew_tolerance_sec"] = 0

        server = _server_save(updated_at="2026-02-17T12:00:00Z")
        local_mtime = datetime(2026, 2, 17, 12, 0, 1, tzinfo=UTC).timestamp()

        result = svc._resolve_conflict_by_mode(local_mtime, server)

        assert result == "upload"

    def test_invalid_server_timestamp_asks(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"

        server = _server_save(updated_at="not-a-timestamp")

        result = svc._resolve_conflict_by_mode(time.time(), server)

        assert result == "ask"

    def test_empty_server_timestamp_asks(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["settings"]["conflict_mode"] = "newest_wins"

        server = _server_save(updated_at="")

        result = svc._resolve_conflict_by_mode(time.time(), server)

        assert result == "ask"


# ---------------------------------------------------------------------------
# TestGetRomSaveInfo
# ---------------------------------------------------------------------------


class TestGetRomSaveInfo:
    """Tests for _get_rom_save_info."""

    def test_returns_info_for_installed_rom(self, tmp_path):
        svc, _ = make_service(tmp_path)
        _install_rom(svc, tmp_path)

        result = svc._get_rom_save_info(42)

        assert result is not None
        system, rom_name, saves_dir = result
        assert system == "gba"
        assert rom_name == "pokemon"
        assert saves_dir.endswith("saves/gba")

    def test_returns_none_for_missing_rom(self, tmp_path):
        svc, _ = make_service(tmp_path)

        result = svc._get_rom_save_info(999)

        assert result is None

    def test_returns_none_for_empty_system(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._state["installed_roms"]["42"] = {
            "rom_id": 42,
            "file_name": "game.gba",
            "file_path": "/some/path.gba",
            "system": "",
            "platform_slug": "",
            "installed_at": "2026-01-01T00:00:00",
        }

        result = svc._get_rom_save_info(42)

        assert result is None


# ---------------------------------------------------------------------------
# TestUploadSpecialChars
# ---------------------------------------------------------------------------


class TestUploadSpecialChars:
    """Upload with special characters (spaces, parentheses) in filename."""

    def test_find_saves_with_special_chars(self, tmp_path):
        svc, _ = make_service(tmp_path)
        rom_name = "Metroid - Zero Mission (USA)"
        file_name = f"{rom_name}.gba"
        _install_rom(svc, tmp_path, rom_id=42, system="gba", file_name=file_name)
        _create_save(tmp_path, system="gba", rom_name=rom_name)

        result = svc._find_save_files(42)

        assert len(result) == 1
        assert result[0]["filename"] == f"{rom_name}.srm"


# ---------------------------------------------------------------------------
# TestUpdateFileSyncState
# ---------------------------------------------------------------------------


class TestUpdateFileSyncState:
    """Tests for _update_file_sync_state."""

    def test_creates_proper_entry(self, tmp_path):
        svc, _ = make_service(tmp_path)
        save_file = _create_save(tmp_path)
        server_resp = {"id": 200, "updated_at": "2026-02-17T15:00:00Z"}

        svc._update_file_sync_state("42", "pokemon.srm", server_resp, str(save_file), "gba")

        entry = svc._save_sync_state["saves"]["42"]["files"]["pokemon.srm"]
        assert entry["last_sync_hash"] == SaveService._file_md5(str(save_file))
        assert entry["last_sync_at"] is not None
        assert entry["last_sync_server_save_id"] == 200


# ---------------------------------------------------------------------------
# TestPruneOrphanedEdgeCase
# ---------------------------------------------------------------------------


class TestPruneOrphanedEdgeCase:
    """Edge case for prune_orphaned_state not covered in TestStateManagement."""

    def test_empty_state_no_crash(self, tmp_path):
        svc, _ = make_service(tmp_path)
        svc._save_sync_state["saves"] = {}
        svc._save_sync_state["playtime"] = {}
        svc._state["shortcut_registry"] = {}

        svc.prune_orphaned_state()  # should not raise

        assert svc._save_sync_state["saves"] == {}
        assert svc._save_sync_state["playtime"] == {}
