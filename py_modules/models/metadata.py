"""ROM metadata and achievement dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RomMetadata:
    """Cached ROM metadata from RomM API."""

    summary: str
    genres: tuple[str, ...]
    companies: tuple[str, ...]
    first_release_date: int | None
    average_rating: float | None
    game_modes: tuple[str, ...]
    player_count: str
    cached_at: float
    steam_categories: tuple[int, ...] = ()  # pre-computed Steam StoreCategory IDs


@dataclass(frozen=True)
class AchievementSummary:
    """Cached achievement progress summary for badge rendering."""

    earned: int
    total: int
    earned_hardcore: int
    cached_at: float
