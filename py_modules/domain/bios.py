"""Pure BIOS-status formatting and computation for the game detail page."""

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


def classify_firmware_file(
    reg_entry: dict | None,
    file_name: str,
    active_core_so: str | None,
) -> tuple[bool, str, str]:
    """Classify a firmware file as required/optional/unknown based on active core.

    Returns (is_required, classification, description).
    """
    if active_core_so and reg_entry and "cores" in reg_entry:
        if active_core_so in reg_entry["cores"]:
            is_required = reg_entry["cores"][active_core_so]["required"]
        else:
            is_required = False
        description = reg_entry.get("description", file_name)
        classification = "required" if is_required else "optional"
    elif reg_entry:
        is_required = reg_entry.get("required", True)
        classification = "required" if is_required else "optional"
        description = reg_entry.get("description", file_name)
    else:
        is_required = False
        classification = "unknown"
        description = file_name
    return is_required, classification, description


def build_cores_info(reg_entry: dict | None) -> dict:
    """Build per-core info dict for frontend display."""
    if not reg_entry or "cores" not in reg_entry:
        return {}
    return {
        core_so_key: {"required": core_data.get("required", True)}
        for core_so_key, core_data in reg_entry["cores"].items()
    }


def is_used_by_active_core(reg_entry: dict | None, active_core_so: str | None) -> bool:
    """Check if a firmware file is used by the active core."""
    if not active_core_so or not reg_entry or "cores" not in reg_entry:
        return True
    return active_core_so in reg_entry["cores"]


def build_file_entry(
    file_name: str,
    downloaded: bool,
    dest: str,
    reg_entry: dict | None,
    active_core_so: str | None,
) -> dict:
    """Build a single file status entry dict."""
    is_required, classification, description = classify_firmware_file(reg_entry, file_name, active_core_so)
    return {
        "file_name": file_name,
        "downloaded": downloaded,
        "local_path": dest,
        "required": is_required,
        "description": description,
        "classification": classification,
        "cores": build_cores_info(reg_entry),
        "used_by_active": is_used_by_active_core(reg_entry, active_core_so),
    }


def collect_firmware_status(
    items: list[dict],
    registry_platform: dict,
    active_core_so: str | None,
) -> list[dict]:
    """Build file entry dicts for a list of pre-resolved firmware items.

    Each item must have keys: file_name, downloaded, dest.
    Looks up reg_entry from registry_platform by file_name and calls
    build_file_entry for each item.
    """
    files = []
    for item in items:
        file_name = item["file_name"]
        reg_entry = registry_platform.get(file_name)
        files.append(build_file_entry(file_name, item["downloaded"], item["dest"], reg_entry, active_core_so))
    return files
