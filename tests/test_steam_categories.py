"""Tests for domain.steam_categories — genre/mode to Steam category mapping."""

from domain.steam_categories import build_steam_categories


class TestBuildSteamCategories:
    def test_always_includes_full_controller_support(self):
        result = build_steam_categories([], [])
        assert 28 in result

    def test_action_genre(self):
        result = build_steam_categories(["Action"], [])
        assert 21 in result
        assert 28 in result

    def test_multiple_genres(self):
        result = build_steam_categories(["Action", "Puzzle"], [])
        assert 21 in result
        assert 4 in result

    def test_game_modes(self):
        result = build_steam_categories([], ["Single player", "Multiplayer"])
        assert 2 in result
        assert 1 in result

    def test_genres_and_modes_combined(self):
        result = build_steam_categories(["Racing"], ["Co-operative"])
        assert 9 in result  # Racing
        assert 9 in result  # Co-operative (same ID as Racing, that's fine)
        assert 28 in result

    def test_unknown_genre_ignored(self):
        result = build_steam_categories(["UnknownGenre"], [])
        assert result == [28]  # only controller support

    def test_rpg_variants(self):
        for name in ["RPG", "Role-playing (RPG)", "Role-playing"]:
            result = build_steam_categories([name], [])
            assert 21 in result

    def test_sport_variants(self):
        for name in ["Sport", "Sports"]:
            result = build_steam_categories([name], [])
            assert 18 in result

    def test_no_duplicates(self):
        result = build_steam_categories(["Action", "RPG"], [])  # both map to 21
        assert result.count(21) == 1
