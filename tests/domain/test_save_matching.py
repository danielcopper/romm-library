"""Tests for domain.save_sync.match_local_to_server_saves — pure function, no I/O."""

from domain.save_sync import match_local_to_server_saves


def _local(fn="pokemon.srm", path="/saves/gba/pokemon.srm"):
    return {"filename": fn, "path": path}


def _server(sid, fn="pokemon.srm", slot="default", updated="2026-03-24T15:00:00", **kw):
    return {"id": sid, "file_name": fn, "slot": slot, "updated_at": updated, "file_size_bytes": 1024, **kw}


class TestTrackedIdMatch:
    def test_matches_by_tracked_save_id(self):
        local = [_local()]
        server = [_server(42, fn="pokemon [timestamp].srm")]
        files_state = {"pokemon.srm": {"tracked_save_id": 42}}

        result = match_local_to_server_saves(local, server, files_state, "default")
        assert len(result.matched) == 1
        assert result.matched[0].match_method == "tracked_id"
        assert result.matched[0].server_save is not None
        assert result.matched[0].server_save["id"] == 42
        assert result.matched[0].filename == "pokemon.srm"

    def test_tracked_id_not_on_server_falls_through(self):
        local = [_local()]
        server = [_server(99, fn="pokemon.srm")]
        files_state = {"pokemon.srm": {"tracked_save_id": 42}}  # 42 not on server

        result = match_local_to_server_saves(local, server, files_state, "default")
        assert result.matched[0].match_method == "filename"
        assert result.matched[0].server_save is not None
        assert result.matched[0].server_save["id"] == 99


class TestFilenameMatch:
    def test_matches_by_filename(self):
        local = [_local()]
        server = [_server(10, fn="pokemon.srm")]
        result = match_local_to_server_saves(local, server, {}, "default")
        assert result.matched[0].match_method == "filename"

    def test_no_match_when_names_differ(self):
        local = [_local()]
        server = [_server(10, fn="other.srm")]
        result = match_local_to_server_saves(local, server, {}, "default")
        # Local file has no match, server file is server-only
        local_match = [m for m in result.matched if m.local_file is not None]
        assert local_match[0].match_method == "slot_fallback" or local_match[0].server_save is not None


class TestSlotFallback:
    def test_fallback_to_newest_in_active_slot(self):
        local = [_local()]
        server = [
            _server(10, fn="pokemon [old].srm", slot="default", updated="2026-03-24T10:00:00"),
            _server(20, fn="pokemon [new].srm", slot="default", updated="2026-03-24T15:00:00"),
        ]
        result = match_local_to_server_saves(local, server, {}, "default")
        assert result.matched[0].match_method == "slot_fallback"
        assert result.matched[0].server_save is not None
        assert result.matched[0].server_save["id"] == 20
        assert result.new_tracked_ids["pokemon.srm"] == 20

    def test_fallback_marks_all_slot_candidates_as_matched(self):
        local = [_local()]
        server = [
            _server(10, fn="a [old].srm", slot="default", updated="2026-03-24T10:00:00"),
            _server(20, fn="a [new].srm", slot="default", updated="2026-03-24T15:00:00"),
        ]
        result = match_local_to_server_saves(local, server, {}, "default")
        assert 10 in result.matched_server_ids
        assert 20 in result.matched_server_ids

    def test_no_fallback_to_different_slot(self):
        local = [_local()]
        server = [_server(10, fn="pokemon [ts].srm", slot="portable")]
        result = match_local_to_server_saves(local, server, {}, "default")
        local_match = [m for m in result.matched if m.local_file is not None]
        # Should NOT match — different slot
        assert local_match[0].server_save is None or local_match[0].match_method != "slot_fallback"


class TestServerOnly:
    def test_downloads_newest_with_local_filename(self):
        server = [
            _server(
                16,
                fn="Mario Golf [2026-03-24_15-18-50].srm",
                slot="default",
                updated="2026-03-24T15:18:50",
                file_name_no_tags="Mario Golf",
                file_extension="srm",
            ),
            _server(
                17,
                fn="Mario Golf [2026-03-24_15-19-15].srm",
                slot="default",
                updated="2026-03-24T15:19:15",
                file_name_no_tags="Mario Golf",
                file_extension="srm",
            ),
            _server(
                18,
                fn="Mario Golf [2026-03-24_15-19-26].srm",
                slot="default",
                updated="2026-03-24T15:19:26",
                file_name_no_tags="Mario Golf",
                file_extension="srm",
            ),
        ]
        result = match_local_to_server_saves([], server, {}, "default", rom_name="Mario Golf")
        server_only = [m for m in result.matched if m.match_method == "server_only"]
        assert len(server_only) == 1
        assert server_only[0].server_save is not None
        assert server_only[0].server_save["id"] == 18
        assert server_only[0].filename == "Mario Golf.srm"

    def test_all_versions_marked_as_matched(self):
        server = [
            _server(
                16,
                fn="a [old].srm",
                slot="default",
                updated="2026-03-24T10:00:00",
                file_name_no_tags="a",
                file_extension="srm",
            ),
            _server(
                18,
                fn="a [new].srm",
                slot="default",
                updated="2026-03-24T15:00:00",
                file_name_no_tags="a",
                file_extension="srm",
            ),
        ]
        result = match_local_to_server_saves([], server, {}, "default")
        assert 16 in result.matched_server_ids
        assert 18 in result.matched_server_ids


class TestOlderVersionSkipping:
    def test_older_versions_not_shown_when_tracked(self):
        """Tracked file matched to id=18 → id=16/17 must not appear as server-only."""
        local = [_local(fn="pokemon.srm")]
        server = [
            _server(16, fn="pokemon [old].srm", slot="default", updated="2026-03-24T10:00:00"),
            _server(17, fn="pokemon [mid].srm", slot="default", updated="2026-03-24T12:00:00"),
            _server(18, fn="pokemon [new].srm", slot="default", updated="2026-03-24T15:00:00"),
        ]
        files_state = {"pokemon.srm": {"tracked_save_id": 18}}

        result = match_local_to_server_saves(local, server, files_state, "default")
        server_only = [m for m in result.matched if m.match_method == "server_only"]
        assert len(server_only) == 0

    def test_different_slot_not_skipped(self):
        """Save in different slot should NOT be skipped."""
        local = [_local(fn="pokemon.srm")]
        server = [
            _server(10, fn="pokemon.srm", slot="default", updated="2026-03-24T15:00:00"),
            _server(
                20,
                fn="pokemon [portable].srm",
                slot="portable",
                updated="2026-03-20T10:00:00",
                file_name_no_tags="pokemon",
                file_extension="srm",
            ),
        ]
        files_state = {"pokemon.srm": {"tracked_save_id": 10}}

        result = match_local_to_server_saves(local, server, files_state, "default")
        server_only = [m for m in result.matched if m.match_method == "server_only"]
        assert len(server_only) == 1
        assert server_only[0].server_save is not None
        assert server_only[0].server_save["id"] == 20


class TestLocalOnly:
    def test_local_file_no_server(self):
        local = [_local()]
        result = match_local_to_server_saves(local, [], {}, "default")
        assert len(result.matched) == 1
        assert result.matched[0].match_method == "local_only"
        assert result.matched[0].server_save is None

    def test_empty_both_sides(self):
        result = match_local_to_server_saves([], [], {}, "default")
        assert len(result.matched) == 0
