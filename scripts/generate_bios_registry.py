#!/usr/bin/env python3
"""Generate defaults/bios_registry.json from libretro-core-info and libretro-database.

Parses .info files for firmware entries (path, opt, desc) and System.dat for
ROM hashes (md5, sha1, size), then merges by filename into a flat registry.

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


def parse_info_files(core_info_dir):
    """Parse all .info files for firmware entries.

    Each .info file may contain numbered firmware entries:
        firmware0_path = "scph5501.bin"
        firmware0_desc = "PS1 US BIOS"
        firmware0_opt  = "true"

    Returns dict: {filename: {"description": str, "required": bool}}
    If multiple cores reference the same file, required wins (OR logic).
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
            # Use basename as key (some paths include subdirs like "pcsx2/bios/")
            filename = os.path.basename(path)
            if not filename:
                continue

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
            else:
                firmware[filename] = {
                    "description": desc,
                    "required": is_required,
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
    """Merge firmware metadata with System.dat hashes by filename.

    Returns the final registry dict.
    """
    files = {}

    # Start with all firmware entries from .info files
    for filename, info in sorted(firmware.items()):
        entry = {
            "description": info.get("description", ""),
            "required": info.get("required", False),
        }
        # Merge hash data if available
        if filename in hashes:
            entry["md5"] = hashes[filename]["md5"]
            entry["sha1"] = hashes[filename]["sha1"]
            entry["size"] = hashes[filename]["size"]
        files[filename] = entry

    # Also include System.dat entries not in any .info file (informational)
    for filename, hash_info in sorted(hashes.items()):
        if filename not in files:
            files[filename] = {
                "description": "",
                "required": False,
                "md5": hash_info["md5"],
                "sha1": hash_info["sha1"],
                "size": hash_info["size"],
            }

    return files


def build_registry(core_info_dir, database_dir):
    """Build the complete BIOS registry."""
    print(f"Parsing .info files from {core_info_dir}...", file=sys.stderr)
    firmware = parse_info_files(core_info_dir)
    print(f"  Found {len(firmware)} firmware entries", file=sys.stderr)

    print(f"Parsing System.dat from {database_dir}...", file=sys.stderr)
    hashes = parse_system_dat(database_dir)
    print(f"  Found {len(hashes)} ROM hash entries", file=sys.stderr)

    files = merge_registry(firmware, hashes)
    print(f"  Merged registry: {len(files)} entries", file=sys.stderr)

    return {
        "_meta": {
            "generated_from": "libretro-core-info + libretro-database System.dat",
            "version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "files": files,
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

    print(f"Wrote {args.output} ({len(registry['files'])} entries)", file=sys.stderr)


if __name__ == "__main__":
    main()
