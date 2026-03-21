"""Genre and game mode to Steam StoreCategory ID mapping.

Maps IGDB genre names and game mode strings to Steam category IDs.
All RomM games get full controller support (category 28).
"""

from __future__ import annotations

GENRE_CATEGORY_MAP: dict[str, int] = {
    "Action": 21,
    "Adventure": 25,
    "RPG": 21,
    "Role-playing (RPG)": 21,
    "Role-playing": 21,
    "Strategy": 2,
    "Simulation": 28,
    "Sport": 18,
    "Sports": 18,
    "Racing": 9,
    "Puzzle": 4,
}

MODE_CATEGORY_MAP: dict[str, int] = {
    "Single player": 2,
    "Multiplayer": 1,
    "Co-operative": 9,
    "Split screen": 24,
    "MMO": 20,
}

FULL_CONTROLLER_SUPPORT = 28


def build_steam_categories(genres: list[str], game_modes: list[str]) -> list[int]:
    """Build list of Steam StoreCategory IDs from genres and game modes."""
    cats: set[int] = {FULL_CONTROLLER_SUPPORT}
    for genre in genres:
        cat = GENRE_CATEGORY_MAP.get(genre)
        if cat is not None:
            cats.add(cat)
    for mode in game_modes:
        cat = MODE_CATEGORY_MAP.get(mode)
        if cat is not None:
            cats.add(cat)
    return sorted(cats)
