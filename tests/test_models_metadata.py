"""Tests for models.metadata dataclasses."""

from dataclasses import asdict

from models.metadata import AchievementSummary, RomMetadata


class TestRomMetadata:
    def test_construction(self):
        m = RomMetadata(
            summary="A great game",
            genres=("Action", "RPG"),
            companies=("Nintendo",),
            first_release_date=946684800,
            average_rating=4.5,
            game_modes=("Single player",),
            player_count="1",
            cached_at=1000.0,
        )
        assert m.summary == "A great game"
        assert m.genres == ("Action", "RPG")

    def test_none_optional_fields(self):
        m = RomMetadata(
            summary="",
            genres=(),
            companies=(),
            first_release_date=None,
            average_rating=None,
            game_modes=(),
            player_count="",
            cached_at=0.0,
        )
        assert m.first_release_date is None
        assert m.average_rating is None

    def test_asdict(self):
        m = RomMetadata(
            summary="Test",
            genres=("Action",),
            companies=(),
            first_release_date=None,
            average_rating=3.0,
            game_modes=("Single player",),
            player_count="1-2",
            cached_at=500.0,
        )
        d = asdict(m)
        assert d["genres"] == ("Action",)
        assert d["cached_at"] == 500.0


class TestAchievementSummary:
    def test_construction(self):
        a = AchievementSummary(earned=5, total=20, earned_hardcore=3, cached_at=9999.0)
        assert a.earned == 5
        assert a.total == 20

    def test_asdict(self):
        a = AchievementSummary(earned=10, total=10, earned_hardcore=10, cached_at=1.0)
        d = asdict(a)
        assert d == {"earned": 10, "total": 10, "earned_hardcore": 10, "cached_at": 1.0}
