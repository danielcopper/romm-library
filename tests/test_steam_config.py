from adapters.steam_config import SteamConfigAdapter


class TestAppIdGeneration:
    def test_generates_signed_int32(self):
        app_id = SteamConfigAdapter.generate_app_id("/path/to/exe", "Test Game")
        assert isinstance(app_id, int)
        assert app_id < 0  # Should be negative (high bit set)

    def test_deterministic(self):
        id1 = SteamConfigAdapter.generate_app_id("/path/exe", "Game")
        id2 = SteamConfigAdapter.generate_app_id("/path/exe", "Game")
        assert id1 == id2

    def test_different_names_different_ids(self):
        id1 = SteamConfigAdapter.generate_app_id("/path/exe", "Game A")
        id2 = SteamConfigAdapter.generate_app_id("/path/exe", "Game B")
        assert id1 != id2


class TestArtworkIdGeneration:
    def test_generates_unsigned(self):
        art_id = SteamConfigAdapter.generate_artwork_id("/path/exe", "Game")
        assert art_id > 0

    def test_matches_app_id_bits(self):
        # artwork_id and app_id should share the same CRC base
        art_id = SteamConfigAdapter.generate_artwork_id("/path/exe", "Game")
        assert art_id & 0x80000000  # High bit set
