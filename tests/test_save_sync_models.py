"""Tests for save sync domain models (dataclasses)."""

from models.save_sync import PlaytimeEntry, SaveConflict, SaveFile


class TestSaveFile:
    def test_minimal_creation(self):
        sf = SaveFile(filename="save.srm", rom_id=42)
        assert sf.filename == "save.srm"
        assert sf.rom_id == 42
        assert sf.local_path is None
        assert sf.local_hash is None
        assert sf.local_mtime is None
        assert sf.local_size is None
        assert sf.server_save_id is None
        assert sf.server_hash is None
        assert sf.server_mtime is None
        assert sf.server_size is None

    def test_full_creation(self):
        sf = SaveFile(
            filename="game.srm",
            rom_id=1,
            local_path="/saves/game.srm",
            local_hash="abc123",
            local_mtime=1000.0,
            local_size=512,
            server_save_id=99,
            server_hash="def456",
            server_mtime="2025-01-01T00:00:00Z",
            server_size=1024,
        )
        assert sf.local_path == "/saves/game.srm"
        assert sf.local_hash == "abc123"
        assert sf.local_mtime == 1000.0
        assert sf.local_size == 512
        assert sf.server_save_id == 99
        assert sf.server_hash == "def456"
        assert sf.server_mtime == "2025-01-01T00:00:00Z"
        assert sf.server_size == 1024

    def test_equality(self):
        a = SaveFile(filename="a.srm", rom_id=1)
        b = SaveFile(filename="a.srm", rom_id=1)
        assert a == b

    def test_inequality(self):
        a = SaveFile(filename="a.srm", rom_id=1)
        b = SaveFile(filename="b.srm", rom_id=1)
        assert a != b


class TestSaveConflict:
    def test_creation(self):
        sc = SaveConflict(
            rom_id=5,
            filename="conflict.srm",
            server_save_id=10,
            local_path="/saves/conflict.srm",
            local_hash="aaa",
            local_mtime=1000.0,
            local_size=256,
            server_hash="bbb",
            server_mtime="2025-06-01T00:00:00Z",
            server_size=512,
        )
        assert sc.rom_id == 5
        assert sc.filename == "conflict.srm"
        assert sc.server_save_id == 10
        assert sc.local_path == "/saves/conflict.srm"
        assert sc.local_hash == "aaa"
        assert sc.local_mtime == 1000.0
        assert sc.local_size == 256
        assert sc.server_hash == "bbb"
        assert sc.server_mtime == "2025-06-01T00:00:00Z"
        assert sc.server_size == 512

    def test_equality(self):
        kwargs = dict(
            rom_id=1,
            filename="f.srm",
            server_save_id=2,
            local_path="/p",
            local_hash="h",
            local_mtime=1.0,
            local_size=1,
            server_hash="s",
            server_mtime="t",
            server_size=2,
        )
        assert SaveConflict(**kwargs) == SaveConflict(**kwargs)


class TestPlaytimeEntry:
    def test_defaults(self):
        pe = PlaytimeEntry(rom_id=7)
        assert pe.rom_id == 7
        assert pe.total_seconds == 0
        assert pe.last_session_start_at is None
        assert pe.last_session_start_unix is None
        assert pe.note_id is None

    def test_full_creation(self):
        pe = PlaytimeEntry(
            rom_id=7,
            total_seconds=3600,
            last_session_start_at="2025-01-01T12:00:00Z",
            last_session_start_unix=1735732800,
            note_id=42,
        )
        assert pe.total_seconds == 3600
        assert pe.last_session_start_at == "2025-01-01T12:00:00Z"
        assert pe.last_session_start_unix == 1735732800
        assert pe.note_id == 42
