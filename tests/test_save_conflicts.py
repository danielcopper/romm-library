"""Unit tests for domain.save_conflicts — pure conflict detection functions."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.save_conflicts import (
    build_conflict_dict,
    check_local_changes,
    check_server_changes_fast,
    detect_conflict_lightweight,
    determine_action,
    resolve_conflict_by_mode,
)

# ---------------------------------------------------------------------------
# TestCheckLocalChanges
# ---------------------------------------------------------------------------


class TestCheckLocalChanges:
    def test_same_hash_returns_false(self):
        assert check_local_changes("abc123", "abc123") is False

    def test_different_hash_returns_true(self):
        assert check_local_changes("abc123", "def456") is True

    def test_empty_local_hash_differs_from_baseline(self):
        assert check_local_changes("", "abc123") is True

    def test_both_empty_returns_false(self):
        assert check_local_changes("", "") is False

    def test_none_local_hash_differs_from_baseline(self):
        assert check_local_changes(None, "abc123") is True

    def test_none_local_hash_matches_none_baseline(self):
        # Unusual edge case — both None means equal
        assert check_local_changes(None, None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestCheckServerChangesFast
# ---------------------------------------------------------------------------


class TestCheckServerChangesFast:
    def _file_state(self, updated_at="2026-02-17T06:00:00Z", size=1024):
        return {
            "last_sync_server_updated_at": updated_at,
            "last_sync_server_size": size,
        }

    def _server_save(self, updated_at="2026-02-17T06:00:00Z", size=1024):
        return {"updated_at": updated_at, "file_size_bytes": size}

    def test_timestamp_and_size_match_returns_false(self):
        file_state = self._file_state()
        server_save = self._server_save()
        result = check_server_changes_fast(file_state, server_save, "hash123")
        assert result is False

    def test_timestamp_matches_size_differs_returns_true(self):
        file_state = self._file_state(size=1024)
        server_save = self._server_save(size=2048)
        result = check_server_changes_fast(file_state, server_save, "hash123")
        assert result is True

    def test_timestamp_changed_returns_none(self):
        file_state = self._file_state(updated_at="2026-02-17T06:00:00Z")
        server_save = self._server_save(updated_at="2026-02-17T12:00:00Z")
        result = check_server_changes_fast(file_state, server_save, "hash123")
        assert result is None

    def test_no_stored_timestamp_returns_none(self):
        file_state = {"last_sync_server_size": 1024}  # no last_sync_server_updated_at
        server_save = self._server_save()
        result = check_server_changes_fast(file_state, server_save, "hash123")
        assert result is None

    def test_empty_file_state_returns_none(self):
        result = check_server_changes_fast({}, self._server_save(), "hash123")
        assert result is None

    def test_stored_size_none_timestamp_matches_returns_false(self):
        """If stored_size is None (legacy), size check is skipped when timestamp matches."""
        file_state = {"last_sync_server_updated_at": "2026-02-17T06:00:00Z", "last_sync_server_size": None}
        server_save = self._server_save(size=2048)
        result = check_server_changes_fast(file_state, server_save, "hash123")
        # stored_size is None — condition `stored_size is not None and ...` is False -> unchanged
        assert result is False

    def test_server_size_none_timestamp_matches_returns_false(self):
        """If server returns no size, size check is skipped."""
        file_state = self._file_state(size=1024)
        server_save = {"updated_at": "2026-02-17T06:00:00Z", "file_size_bytes": None}
        result = check_server_changes_fast(file_state, server_save, "hash123")
        assert result is False


# ---------------------------------------------------------------------------
# TestDetermineAction
# ---------------------------------------------------------------------------


class TestDetermineAction:
    def test_neither_changed_skips(self):
        assert determine_action(False, False) == "skip"

    def test_only_server_changed_downloads(self):
        assert determine_action(False, True) == "download"

    def test_only_local_changed_uploads(self):
        assert determine_action(True, False) == "upload"

    def test_both_changed_conflicts(self):
        assert determine_action(True, True) == "conflict"


# ---------------------------------------------------------------------------
# TestDetectConflictLightweight
# ---------------------------------------------------------------------------


class TestDetectConflictLightweight:
    def _server_save(self, updated_at="2026-02-17T06:00:00Z", size=1024):
        return {"updated_at": updated_at, "file_size_bytes": size}

    def test_never_synced_no_server_uploads(self):
        result = detect_conflict_lightweight(1000.0, 1024, None, {})
        assert result == "upload"

    def test_never_synced_with_server_conflicts(self):
        result = detect_conflict_lightweight(1000.0, 1024, self._server_save(), {})
        assert result == "conflict"

    def test_skip_when_unchanged(self):
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
            "last_sync_server_size": 1024,
        }
        result = detect_conflict_lightweight(1000.0, 1024, self._server_save(), file_state)
        assert result == "skip"

    def test_local_only_changed_uploads(self):
        file_state = {"last_sync_hash": "abc", "last_sync_local_mtime": 1000.0}
        result = detect_conflict_lightweight(2000.0, 1024, None, file_state)
        assert result == "upload"

    def test_server_only_changed_downloads(self):
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = self._server_save(updated_at="2026-02-17T08:00:00Z")
        result = detect_conflict_lightweight(1000.0, 1024, server, file_state)
        assert result == "download"

    def test_both_changed_conflicts(self):
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T04:00:00Z",
            "last_sync_server_size": 1024,
        }
        server = self._server_save(updated_at="2026-02-17T08:00:00Z")
        result = detect_conflict_lightweight(2000.0, 1024, server, file_state)
        assert result == "conflict"

    def test_no_server_save_only_local_changed_uploads(self):
        file_state = {"last_sync_hash": "abc", "last_sync_local_mtime": 1000.0}
        result = detect_conflict_lightweight(2000.0, 1024, None, file_state)
        assert result == "upload"

    def test_mtime_within_tolerance_unchanged(self):
        """Mtime difference <= 1.0 second is treated as unchanged."""
        file_state = {"last_sync_hash": "abc", "last_sync_local_mtime": 1000.0}
        result = detect_conflict_lightweight(1000.5, 1024, None, file_state)
        assert result == "skip"

    def test_fallback_to_size_when_no_mtime(self):
        """No stored mtime: size change counts as local changed."""
        file_state = {"last_sync_hash": "abc", "last_sync_local_size": 1024}
        result = detect_conflict_lightweight(1000.0, 2048, None, file_state)
        assert result == "upload"

    def test_fallback_size_unchanged_skips(self):
        """No stored mtime, same size: local unchanged."""
        file_state = {"last_sync_hash": "abc", "last_sync_local_size": 1024}
        result = detect_conflict_lightweight(1000.0, 1024, None, file_state)
        assert result == "skip"

    def test_server_size_change_triggers_server_changed(self):
        """Same timestamp but different size -> server changed."""
        file_state = {
            "last_sync_hash": "abc",
            "last_sync_local_mtime": 1000.0,
            "last_sync_server_updated_at": "2026-02-17T06:00:00Z",
            "last_sync_server_size": 1024,
        }
        result = detect_conflict_lightweight(1000.0, 1024, self._server_save(size=2048), file_state)
        assert result == "download"


# ---------------------------------------------------------------------------
# TestResolveConflictByMode
# ---------------------------------------------------------------------------


class TestResolveConflictByMode:
    def _server_save(self, updated_at="2026-02-17T06:00:00Z"):
        return {"updated_at": updated_at}

    def test_ask_me_returns_ask(self):
        result = resolve_conflict_by_mode("ask_me", 1000.0, self._server_save())
        assert result == "ask"

    def test_always_upload_returns_upload(self):
        result = resolve_conflict_by_mode("always_upload", 1000.0, self._server_save())
        assert result == "upload"

    def test_always_download_returns_download(self):
        result = resolve_conflict_by_mode("always_download", 1000.0, self._server_save())
        assert result == "download"

    def test_newest_wins_local_newer_uploads(self):
        # Server updated at 2026-02-17T06:00:00Z
        # local_mtime is after that
        server_dt = datetime(2026, 2, 17, 6, 0, 0, tzinfo=timezone.utc)
        local_mtime = server_dt.timestamp() + 3600  # 1 hour later
        result = resolve_conflict_by_mode("newest_wins", local_mtime, self._server_save(), tolerance=60)
        assert result == "upload"

    def test_newest_wins_server_newer_downloads(self):
        server_dt = datetime(2026, 2, 17, 6, 0, 0, tzinfo=timezone.utc)
        local_mtime = server_dt.timestamp() - 3600  # 1 hour earlier
        result = resolve_conflict_by_mode("newest_wins", local_mtime, self._server_save(), tolerance=60)
        assert result == "download"

    def test_newest_wins_within_tolerance_asks(self):
        server_dt = datetime(2026, 2, 17, 6, 0, 0, tzinfo=timezone.utc)
        local_mtime = server_dt.timestamp() + 30  # 30s later, within 60s tolerance
        result = resolve_conflict_by_mode("newest_wins", local_mtime, self._server_save(), tolerance=60)
        assert result == "ask"

    def test_newest_wins_invalid_server_date_asks(self):
        result = resolve_conflict_by_mode("newest_wins", 1000.0, {"updated_at": "not-a-date"}, tolerance=60)
        assert result == "ask"

    def test_newest_wins_missing_server_date_asks(self):
        result = resolve_conflict_by_mode("newest_wins", 1000.0, {}, tolerance=60)
        assert result == "ask"

    def test_unknown_mode_falls_through_to_newest_wins(self):
        """Unrecognised mode falls through to newest_wins logic."""
        server_dt = datetime(2026, 2, 17, 6, 0, 0, tzinfo=timezone.utc)
        local_mtime = server_dt.timestamp() + 3600
        result = resolve_conflict_by_mode("some_future_mode", local_mtime, self._server_save(), tolerance=60)
        assert result == "upload"


# ---------------------------------------------------------------------------
# TestBuildConflictDict
# ---------------------------------------------------------------------------


class TestBuildConflictDict:
    def _server_save(self):
        return {
            "id": 100,
            "updated_at": "2026-02-17T06:00:00Z",
            "file_size_bytes": 1024,
        }

    def test_full_dict_structure(self):
        local_mtime = datetime(2026, 2, 17, 5, 0, 0, tzinfo=timezone.utc).timestamp()
        local_info = {"path": "/saves/pokemon.srm", "mtime": local_mtime, "size": 1024}
        result = build_conflict_dict(42, "pokemon.srm", local_info, "abc123", self._server_save())

        assert result["rom_id"] == 42
        assert result["filename"] == "pokemon.srm"
        assert result["local_path"] == "/saves/pokemon.srm"
        assert result["local_hash"] == "abc123"
        assert result["local_mtime"] == "2026-02-17T05:00:00+00:00"
        assert result["local_size"] == 1024
        assert result["server_save_id"] == 100
        assert result["server_updated_at"] == "2026-02-17T06:00:00Z"
        assert result["server_size"] == 1024
        assert "created_at" in result

    def test_no_local_info(self):
        result = build_conflict_dict(42, "pokemon.srm", None, None, self._server_save())
        assert result["local_path"] is None
        assert result["local_hash"] is None
        assert result["local_mtime"] is None
        assert result["local_size"] is None

    def test_local_mtime_none(self):
        local_info = {"path": "/saves/pokemon.srm", "mtime": None, "size": 1024}
        result = build_conflict_dict(42, "pokemon.srm", local_info, "abc123", self._server_save())
        assert result["local_mtime"] is None

    def test_missing_local_mtime_key(self):
        """local_info without mtime key — treated as None."""
        local_info = {"path": "/saves/pokemon.srm", "size": 1024}
        result = build_conflict_dict(42, "pokemon.srm", local_info, "abc123", self._server_save())
        assert result["local_mtime"] is None

    def test_server_missing_optional_fields(self):
        server = {"id": 99}
        local_info = {"path": "/saves/pokemon.srm", "mtime": None, "size": 0}
        result = build_conflict_dict(42, "pokemon.srm", local_info, "hash", server)
        assert result["server_save_id"] == 99
        assert result["server_updated_at"] == ""
        assert result["server_size"] is None

    def test_created_at_is_utc_iso(self):
        local_info = {"path": "/saves/pokemon.srm", "mtime": None, "size": 0}
        result = build_conflict_dict(1, "f.srm", local_info, None, self._server_save())
        # Should parse without error
        datetime.fromisoformat(result["created_at"])
