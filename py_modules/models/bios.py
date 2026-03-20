"""BIOS/firmware status dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AvailableCore:
    """A RetroArch core available for a platform."""

    core_so: str
    label: str
    is_default: bool


@dataclass(frozen=True)
class BiosFileEntry:
    """Status of a single BIOS/firmware file."""

    file_name: str
    downloaded: bool
    local_path: str
    required: bool
    description: str
    classification: str  # "required" | "optional" | "unknown"
    cores: dict[str, dict]  # {core_so: {"required": bool}}
    used_by_active: bool


@dataclass(frozen=True)
class BiosStatus:
    """Aggregated BIOS status for a platform, ready for frontend display."""

    platform_slug: str
    total: int
    downloaded: int
    all_downloaded: bool
    required_count: int | None
    required_downloaded: int | None
    files: tuple[BiosFileEntry, ...]
    active_core: str | None
    active_core_label: str | None
    available_cores: tuple[AvailableCore, ...]
    cached_at: float = 0.0
