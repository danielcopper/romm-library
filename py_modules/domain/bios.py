"""Pure BIOS-status formatting and computation for the game detail page."""

from __future__ import annotations

from models.bios import AvailableCore, BiosFileEntry, BiosStatus


def format_bios_status(bios: dict, platform_slug: str) -> BiosStatus:
    """Build a frontend-ready BiosStatus dataclass from raw firmware check result."""
    raw_files = bios.get("files", [])
    if raw_files and isinstance(raw_files[0], dict):
        files: tuple[BiosFileEntry, ...] = tuple(
            BiosFileEntry(
                file_name=f.get("file_name", ""),
                downloaded=f.get("downloaded", False),
                local_path=f.get("local_path", ""),
                required=f.get("required", False),
                description=f.get("description", ""),
                classification=f.get("classification", "unknown"),
                cores=f.get("cores", {}),
                used_by_active=f.get("used_by_active", True),
            )
            for f in raw_files
        )
    else:
        files = tuple(raw_files)

    raw_cores = bios.get("available_cores", [])
    available_cores: tuple[AvailableCore, ...] = tuple(
        AvailableCore(
            core_so=c.get("core_so", c.get("core", "")),
            label=c.get("label", ""),
            is_default=c.get("is_default", False),
        )
        for c in raw_cores
    )

    return BiosStatus(
        platform_slug=platform_slug,
        server_count=bios.get("server_count", 0),
        local_count=bios.get("local_count", 0),
        all_downloaded=bios.get("all_downloaded", False),
        required_count=bios.get("required_count"),
        required_downloaded=bios.get("required_downloaded"),
        files=files,
        active_core=bios.get("active_core"),
        active_core_label=bios.get("active_core_label"),
        available_cores=available_cores,
    )


def classify_firmware_file(
    reg_entry: dict | None,
    file_name: str,
    active_core_so: str | None,
) -> tuple[bool, str, str]:
    """Classify a firmware file as required/optional/unknown based on active core.

    Returns (is_required, classification, description).
    """
    if active_core_so and reg_entry and "cores" in reg_entry:
        is_required = reg_entry["cores"][active_core_so]["required"] if active_core_so in reg_entry["cores"] else False
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
) -> BiosFileEntry:
    """Build a single file status entry as a BiosFileEntry dataclass."""
    is_required, classification, description = classify_firmware_file(reg_entry, file_name, active_core_so)
    return BiosFileEntry(
        file_name=file_name,
        downloaded=downloaded,
        local_path=dest,
        required=is_required,
        description=description,
        classification=classification,
        cores=build_cores_info(reg_entry),
        used_by_active=is_used_by_active_core(reg_entry, active_core_so),
    )


def collect_firmware_status(
    items: list[dict],
    registry_platform: dict,
    active_core_so: str | None,
) -> tuple[BiosFileEntry, ...]:
    """Build BiosFileEntry objects for a list of pre-resolved firmware items.

    Each item must have keys: file_name, downloaded, dest.
    Looks up reg_entry from registry_platform by file_name and calls
    build_file_entry for each item.
    """
    return tuple(
        build_file_entry(
            item["file_name"],
            item["downloaded"],
            item["dest"],
            registry_platform.get(item["file_name"]),
            active_core_so,
        )
        for item in items
    )
