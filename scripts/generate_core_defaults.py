#!/usr/bin/env python3
"""Generate defaults/core_defaults.json from RetroDECK's es_systems.xml.

Parses each <system> element, extracts RetroArch core mappings from <command>
elements, and produces a static JSON mapping of system slug -> default core.

Usage:
    python scripts/generate_core_defaults.py \
        --es-systems-xml /path/to/es_systems.xml \
        -o defaults/core_defaults.json

The XML file is bundled with RetroDECK's ES-DE component:
    /var/lib/flatpak/app/net.retrodeck.retrodeck/.../es_systems.xml
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Regex to extract the .so basename from a RetroArch core path.
# Core names may contain alphanumerics, underscores, and hyphens
# (e.g. mesen-s_libretro, bsnes-jg_libretro, vitaquake2-rogue_libretro).
CORE_RE = re.compile(r"%CORE_RETROARCH%/([\w-]+_libretro)\.so")


def strip_xml_comments(xml_text: str) -> str:
    """Remove XML comments so that commented-out <command> elements are not parsed.

    ElementTree does not parse comments as elements, but entire <system> blocks
    can be commented out.  We strip comments before parsing to be safe.
    """
    return re.sub(r"<!--.*?-->", "", xml_text, flags=re.DOTALL)


def parse_es_systems(xml_path: str) -> dict:
    """Parse es_systems.xml and return the core_defaults structure."""
    with open(xml_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Strip XML comments so commented-out systems/commands are ignored.
    cleaned = strip_xml_comments(raw)

    root = ET.fromstring(cleaned)
    systems = {}

    for system_el in root.findall("system"):
        name_el = system_el.find("name")
        if name_el is None or not name_el.text:
            continue
        slug = name_el.text.strip()

        cores = {}  # core_so_name -> label
        default_core = None
        default_label = None

        for cmd_el in system_el.findall("command"):
            label = cmd_el.get("label", "")
            text = cmd_el.text or ""

            m = CORE_RE.search(text)
            if m:
                core_name = m.group(1)
                cores[core_name] = label
                # First RetroArch core encountered is the default.
                if default_core is None:
                    default_core = core_name
                    default_label = label

        systems[slug] = {
            "default_core": default_core,
            "default_label": default_label,
            "cores": cores,
        }

    return systems


def main():
    parser = argparse.ArgumentParser(
        description="Generate core_defaults.json from es_systems.xml"
    )
    parser.add_argument(
        "--es-systems-xml",
        required=True,
        help="Path to RetroDECK's es_systems.xml",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="defaults/core_defaults.json",
        help="Output JSON path (default: defaults/core_defaults.json)",
    )
    args = parser.parse_args()

    systems = parse_es_systems(args.es_systems_xml)

    output = {
        "_meta": {
            "generated_from": "es_systems.xml",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "systems": systems,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Summary stats
    total = len(systems)
    with_cores = sum(1 for s in systems.values() if s["default_core"])
    standalone_only = total - with_cores
    print(f"Wrote {args.output}: {total} systems ({with_cores} with RetroArch cores, {standalone_only} standalone-only)")


if __name__ == "__main__":
    main()
