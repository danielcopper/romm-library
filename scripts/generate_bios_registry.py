#!/usr/bin/env python3
"""Generate defaults/bios_registry.json from libretro-core-info and libretro-database.

Parses .info files for firmware entries (path, opt, desc) and their systemname,
then merges with System.dat hashes and groups by platform slug.

Usage:
    python scripts/generate_bios_registry.py \
        --core-info /path/to/libretro-core-info \
        --database /path/to/libretro-database \
        -o defaults/bios_registry.json

Requirements:
    - A checkout of https://github.com/libretro/libretro-core-info
    - A checkout of https://github.com/libretro/libretro-database
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone


# Maps libretro systemname strings to our platform slugs.
# Updated for current libretro-core-info naming conventions.
# Multiple systemname variants may map to the same slug.
SYSTEMNAME_TO_SLUG = {
    # PlayStation
    "Sony - PlayStation": "psx",
    "PlayStation": "psx",
    "Sony PlayStation 2": "ps2",
    "PSP": "psp",
    # Sega
    "Sega - Dreamcast": "dc",
    "Sega Dreamcast": "dc",
    "Sega - Saturn": "saturn",
    "Saturn": "saturn",
    "Sega - Mega-CD - Sega CD": "segacd",
    "Sega - Master System - Mark III": "sms",
    "Sega Master System": "sms",
    "Sega 8-bit": "sms",
    "Sega 8-bit (MS/GG/SG-1000)": "sms",
    "Sega - Game Gear": "gg",
    "Sega - Mega Drive - Genesis": "genesis",
    "Sega Genesis": "genesis",
    "Sega 8/16-bit (Various)": "genesis",
    "Sega 8/16-bit + 32X (Various)": "genesis",
    # Nintendo
    "Nintendo - Game Boy": "gb",
    "Nintendo - Game Boy Color": "gbc",
    "Game Boy/Game Boy Color": "gb",
    "Nintendo - Game Boy Advance": "gba",
    "Game Boy Advance": "gba",
    "Game Boy/Game Boy Color/Game Boy Advance": "gba",
    "Nintendo - Nintendo DS": "nds",
    "Nintendo DS": "nds",
    "Nintendo - Famicom Disk System": "fds",
    "Nintendo - Nintendo Entertainment System": "nes",
    "Nintendo Entertainment System": "nes",
    "Nintendo 64": "n64",
    "Super Nintendo Entertainment System": "snes",
    "Super Nintendo Entertainment System / Game Boy / Game Boy Color": "snes",
    "GameCube / Wii": "gc",
    # Atari
    "Atari - Lynx": "lynx",
    "Lynx": "lynx",
    "Atari - 5200": "atari5200",
    "Atari 5200": "atari5200",
    "Atari - 7800": "atari7800",
    "Atari 7800": "atari7800",
    "Atari - 8-bit": "atari800",
    "Atari 8-bit Family": "atari800",
    "Atari - ST": "atarist",
    "Atari ST/STE/TT/Falcon": "atarist",
    # NEC
    "NEC - PC Engine - TurboGrafx 16": "pce",
    "PC Engine/PCE-CD": "pce",
    "PC Engine SuperGrafx": "pce",
    "PC Engine/SuperGrafx": "pce",
    "PC Engine/SuperGrafx/CD": "pce",
    "PC-FX": "pcfx",
    "PC-98": "pc98",
    # SNK
    "SNK - Neo Geo": "neogeo",
    "Neo Geo": "neogeo",
    "SNK Neo Geo CD": "neogeocd",
    # Commodore
    "Commodore - Amiga": "amiga",
    "Amiga": "amiga",
    "C64": "c64",
    "C64 SuperCPU": "c64",
    "C64DTV": "c64",
    "C128": "c128",
    "128": "c128",
    # Other
    "Coleco - ColecoVision": "colecovision",
    "ColecoVision": "colecovision",
    "ColecoVision/CreatiVision/My Vision": "colecovision",
    "Microsoft - MSX": "msx",
    "MSX": "msx",
    "MSX/SVI/ColecoVision/SG-1000": "msx",
    "Amstrad - CPC": "amstradcpc",
    "The 3DO Company - 3DO": "3do",
    "3DO": "3do",
    "Magnavox - Odyssey2": "odyssey2",
    "Magnavox Odyssey2 / Philips Videopac+": "odyssey2",
    "CD-i": "cdi",
    "CDi": "cdi",
    "Intellivision": "intellivision",
    "DOS": "dos",
    "PC-8000 / PC-8800 series": "pc88",
    "Sharp X1": "x1",
    "Sharp X68000": "x68000",
    "Pokemon Mini": "pokemini",
    "Mac68k": "mac68k",
    "BK-0010/BK-0011(M)": "bk",
    "TI83": "ti83",
    "Super Cassette Vision": "scv",
    "FreeChaF": "channelf",
    "Vircon32": "vircon32",
    "Palm OS": "palmos",
    "CP System I/II": "cps",
    # Multi-system / game engines — group under _unknown
    "Arcade (various)": "_arcade",
    "Game engine": "_engine",
    "RPG Maker XP/VX/VX Ace Game Engine": "_engine",
    "Wolfenstein 3D Game Engine": "_engine",
    "J2ME": "j2me",
    "Java ME": "j2me",
    "ZX Spectrum (various)": "zxspectrum",
}


def systemname_to_slug(systemname):
    """Convert a libretro systemname to a platform slug.

    Uses the SYSTEMNAME_TO_SLUG mapping. For unknown system names, generates
    a slugified version and logs a warning.
    """
    if systemname in SYSTEMNAME_TO_SLUG:
        return SYSTEMNAME_TO_SLUG[systemname]

    # Slugify: lowercase, replace non-alphanumeric with hyphens, collapse
    slug = re.sub(r"[^a-z0-9]+", "-", systemname.lower()).strip("-")
    print(f"Warning: unknown systemname '{systemname}', using slug '{slug}'", file=sys.stderr)
    return slug


def parse_info_files(core_info_dir):
    """Parse all .info files for firmware entries with system name.

    Each .info file may contain:
        systemname = "Sony - PlayStation"
        firmware0_path = "scph5501.bin"
        firmware0_desc = "PS1 US BIOS"
        firmware0_opt  = "true"

    Returns dict: {filename: {"description": str, "required": bool, "firmware_path": str, "systems": set}}
    If multiple cores reference the same file, required wins (OR logic).
    The systems set tracks all system names that reference this file.
    The firmware_path preserves the full relative path from the .info file
    (e.g. "dc/dc_boot.bin" for Dreamcast, "scph5501.bin" for PSX).
    When multiple cores reference the same file with different paths,
    the longest path (with subdirectory) takes precedence.
    """
    firmware = {}

    for fname in os.listdir(core_info_dir):
        if not fname.endswith(".info"):
            continue
        filepath = os.path.join(core_info_dir, fname)
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            print(f"Warning: cannot read {filepath}: {e}", file=sys.stderr)
            continue

        # Extract systemname for this core
        sn_match = re.search(r'^systemname\s*=\s*"([^"]*)"', content, re.MULTILINE)
        systemname = sn_match.group(1) if sn_match else ""

        # Collect all firmware entries by index
        paths = {}
        descs = {}
        opts = {}

        for match in re.finditer(
            r'^firmware(\d+)_path\s*=\s*"([^"]*)"', content, re.MULTILINE
        ):
            idx, path = match.group(1), match.group(2)
            paths[idx] = path

        for match in re.finditer(
            r'^firmware(\d+)_desc\s*=\s*"([^"]*)"', content, re.MULTILINE
        ):
            idx, desc = match.group(1), match.group(2)
            descs[idx] = desc

        for match in re.finditer(
            r'^firmware(\d+)_opt\s*=\s*"([^"]*)"', content, re.MULTILINE
        ):
            idx, opt = match.group(1), match.group(2)
            opts[idx] = opt

        for idx, path in paths.items():
            # Use basename as key for dedup/lookup
            filename = os.path.basename(path)
            if not filename:
                continue

            # Preserve the full relative path from the .info file
            firmware_path = path

            desc = descs.get(idx, "")
            # If opt is missing, libretro assumes required
            is_optional = opts.get(idx, "false").lower() == "true"
            is_required = not is_optional

            if filename in firmware:
                # OR logic: if ANY core says required, it's required
                if is_required:
                    firmware[filename]["required"] = True
                # Keep longer/better description
                if len(desc) > len(firmware[filename].get("description", "")):
                    firmware[filename]["description"] = desc
                # Keep the longest firmware_path (the one with subdirectory wins)
                if len(firmware_path) > len(firmware[filename].get("firmware_path", "")):
                    firmware[filename]["firmware_path"] = firmware_path
                # Track all systems that reference this file
                if systemname:
                    firmware[filename]["systems"].add(systemname)
            else:
                firmware[filename] = {
                    "description": desc,
                    "required": is_required,
                    "firmware_path": firmware_path,
                    "systems": {systemname} if systemname else set(),
                }

    return firmware


def parse_system_dat(database_dir):
    """Parse dat/System.dat for ROM entries with hashes.

    Format:
        rom ( name "filename.bin" size 524288 crc AABBCCDD md5 ... sha1 ... )
    or without quotes:
        rom ( name filename.bin size 524288 crc AABBCCDD md5 ... sha1 ... )

    Returns dict: {filename: {"size": int, "md5": str, "sha1": str}}
    """
    dat_path = os.path.join(database_dir, "dat", "System.dat")
    if not os.path.isfile(dat_path):
        print(f"Warning: {dat_path} not found", file=sys.stderr)
        return {}

    try:
        with open(dat_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        print(f"Warning: cannot read {dat_path}: {e}", file=sys.stderr)
        return {}

    hashes = {}
    # Match rom entries — name may or may not be quoted
    pattern = re.compile(
        r'rom\s*\(\s*name\s+"?([^")\s]+)"?\s+'
        r'size\s+(\d+)\s+'
        r'crc\s+([0-9A-Fa-f]+)\s+'
        r'md5\s+([0-9a-f]+)\s+'
        r'sha1\s+([0-9a-f]+)\s*\)'
    )

    for match in pattern.finditer(content):
        name = match.group(1)
        size = int(match.group(2))
        md5 = match.group(4)
        sha1 = match.group(5)
        hashes[name] = {"size": size, "md5": md5, "sha1": sha1}

    return hashes


def merge_registry(firmware, hashes):
    """Merge firmware metadata with System.dat hashes, grouped by platform.

    Returns dict: {slug: {filename: {entry_data}}}
    Files with no system association go under "_unknown".
    Files appearing in multiple systems are included under all relevant platforms.
    """
    platforms = {}

    def add_to_platform(slug, filename, entry):
        if slug not in platforms:
            platforms[slug] = {}
        # If file already exists under this platform, merge (OR required)
        if filename in platforms[slug]:
            if entry.get("required"):
                platforms[slug][filename]["required"] = True
            if len(entry.get("description", "")) > len(platforms[slug][filename].get("description", "")):
                platforms[slug][filename]["description"] = entry["description"]
        else:
            platforms[slug][filename] = entry

    # Process firmware entries from .info files
    for filename, info in sorted(firmware.items()):
        entry = {
            "description": info.get("description", ""),
            "required": info.get("required", False),
            "firmware_path": info.get("firmware_path", filename),
        }
        # Merge hash data if available
        if filename in hashes:
            entry["md5"] = hashes[filename]["md5"]
            entry["sha1"] = hashes[filename]["sha1"]
            entry["size"] = hashes[filename]["size"]

        systems = info.get("systems", set())
        if systems:
            for systemname in systems:
                slug = systemname_to_slug(systemname)
                add_to_platform(slug, filename, dict(entry))
        else:
            add_to_platform("_unknown", filename, entry)

    # Also include System.dat entries not in any .info file (informational)
    for filename, hash_info in sorted(hashes.items()):
        already_added = any(filename in plat_files for plat_files in platforms.values())
        if not already_added:
            entry = {
                "description": "",
                "required": False,
                "firmware_path": filename,
                "md5": hash_info["md5"],
                "sha1": hash_info["sha1"],
                "size": hash_info["size"],
            }
            add_to_platform("_unknown", filename, entry)

    # Sort files within each platform
    return {slug: dict(sorted(files.items())) for slug, files in sorted(platforms.items())}


def build_registry(core_info_dir, database_dir):
    """Build the complete BIOS registry grouped by platform."""
    print(f"Parsing .info files from {core_info_dir}...", file=sys.stderr)
    firmware = parse_info_files(core_info_dir)
    print(f"  Found {len(firmware)} firmware entries", file=sys.stderr)

    print(f"Parsing System.dat from {database_dir}...", file=sys.stderr)
    hashes = parse_system_dat(database_dir)
    print(f"  Found {len(hashes)} ROM hash entries", file=sys.stderr)

    platforms = merge_registry(firmware, hashes)
    total_files = sum(len(files) for files in platforms.values())
    print(f"  Merged registry: {total_files} entries across {len(platforms)} platforms", file=sys.stderr)

    return {
        "_meta": {
            "generated_from": "libretro-core-info + libretro-database System.dat",
            "version": "3.0.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "platforms": platforms,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate BIOS registry from libretro data.",
        epilog=(
            "Example:\n"
            "  python scripts/generate_bios_registry.py \\\n"
            "    --core-info ~/src/libretro-core-info \\\n"
            "    --database ~/src/libretro-database \\\n"
            "    -o defaults/bios_registry.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--core-info",
        required=True,
        help="Path to libretro-core-info checkout",
    )
    parser.add_argument(
        "--database",
        required=True,
        help="Path to libretro-database checkout",
    )
    parser.add_argument(
        "-o", "--output",
        default="defaults/bios_registry.json",
        help="Output JSON path (default: defaults/bios_registry.json)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.core_info):
        parser.error(f"core-info directory not found: {args.core_info}")
    if not os.path.isdir(args.database):
        parser.error(f"database directory not found: {args.database}")

    registry = build_registry(args.core_info, args.database)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(files) for files in registry["platforms"].values())
    print(f"Wrote {args.output} ({total} entries across {len(registry['platforms'])} platforms)", file=sys.stderr)


if __name__ == "__main__":
    main()
