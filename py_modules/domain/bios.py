"""Pure BIOS-status formatting for the game detail page."""

from __future__ import annotations


def format_bios_status(bios: dict, platform_slug: str) -> dict:
    """Build a frontend-ready BIOS status dict from raw firmware check result."""
    return {
        "platform_slug": platform_slug,
        "total": bios.get("server_count", 0),
        "downloaded": bios.get("local_count", 0),
        "all_downloaded": bios.get("all_downloaded", False),
        "required_count": bios.get("required_count"),
        "required_downloaded": bios.get("required_downloaded"),
        "files": bios.get("files", []),
        "active_core": bios.get("active_core"),
        "active_core_label": bios.get("active_core_label"),
        "available_cores": bios.get("available_cores", []),
    }
