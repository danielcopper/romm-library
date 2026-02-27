"""ES-DE configuration parser for active core resolution."""

import glob
import json
import os
import re
import xml.etree.ElementTree as ET

import decky  # for DECKY_USER_HOME and logging


# Module-level caches
_es_systems_cache = None  # dict or None
_core_defaults_cache = None  # dict or None

_CORE_SO_RE = re.compile(r"%CORE_RETROARCH%/([\w-]+_libretro)\.so")

_FLATPAK_GLOB = "/var/lib/flatpak/app/net.retrodeck.retrodeck/*/files/retrodeck/components/es-de/share/es-de/resources/systems/linux/es_systems.xml"


def _reset_cache():
    """Reset caches (for testing)."""
    global _es_systems_cache, _core_defaults_cache
    _es_systems_cache = None
    _core_defaults_cache = None


def find_es_systems_xml():
    """Locate es_systems.xml inside the RetroDECK flatpak installation.

    Returns the path or None.
    """
    matches = glob.glob(_FLATPAK_GLOB)
    return matches[0] if matches else None


def parse_es_systems(xml_path):
    """Parse es_systems.xml and return per-system core info.

    Returns: {system_name: {
        "default_core": str | None,
        "default_label": str | None,
        "cores": {core_so: label},
        "label_to_core": {label: core_so},
    }}

    Returns empty dict if file can't be parsed or fails structural validation.
    """
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError) as e:
        decky.logger.warning("es_de_config: failed to parse %s: %s", xml_path, e)
        return {}

    root = tree.getroot()
    if root.tag != "systemList":
        decky.logger.warning("es_de_config: unexpected root tag '%s' (expected 'systemList')", root.tag)
        return {}

    systems = {}
    for system_el in root.findall("system"):
        name_el = system_el.find("name")
        if name_el is None or not name_el.text:
            continue

        system_name = name_el.text.strip()
        cores = {}  # core_so -> label
        label_to_core = {}  # label -> core_so
        default_core = None
        default_label = None

        for cmd_el in system_el.findall("command"):
            label = cmd_el.get("label", "")
            cmd_text = cmd_el.text or ""

            match = _CORE_SO_RE.search(cmd_text)
            if match:
                core_so = match.group(1)
                cores[core_so] = label
                label_to_core[label] = core_so
                if default_core is None:
                    default_core = core_so
                    default_label = label

        systems[system_name] = {
            "default_core": default_core,
            "default_label": default_label,
            "cores": cores,
            "label_to_core": label_to_core,
        }

    return systems


def _load_core_defaults():
    """Load the static core_defaults.json fallback."""
    global _core_defaults_cache
    if _core_defaults_cache is not None:
        return _core_defaults_cache

    defaults_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "defaults", "core_defaults.json")
    try:
        with open(defaults_path, "r") as f:
            data = json.load(f)
        _core_defaults_cache = data.get("systems", {})
    except (OSError, json.JSONDecodeError) as e:
        decky.logger.warning("es_de_config: failed to load core_defaults.json: %s", e)
        _core_defaults_cache = {}

    return _core_defaults_cache


def _load_es_systems():
    """Load and cache es_systems.xml parse result."""
    global _es_systems_cache
    if _es_systems_cache is not None:
        return _es_systems_cache

    xml_path = find_es_systems_xml()
    if xml_path:
        _es_systems_cache = parse_es_systems(xml_path)
    else:
        decky.logger.info("es_de_config: es_systems.xml not found, using core_defaults.json fallback")
        _es_systems_cache = {}

    return _es_systems_cache


def get_system_override(retrodeck_home, system_name):
    """Check for per-system alternative emulator override in gamelist.xml.

    Reads {retrodeck_home}/ES-DE/gamelists/{system}/gamelist.xml
    looking for <alternativeEmulator><label>X</label></alternativeEmulator>.

    Returns the label string or None.
    """
    gamelist_path = os.path.join(retrodeck_home, "ES-DE", "gamelists", system_name, "gamelist.xml")
    if not os.path.exists(gamelist_path):
        return None

    try:
        tree = ET.parse(gamelist_path)
        root = tree.getroot()
        alt_emu = root.find("alternativeEmulator")
        if alt_emu is not None:
            label_el = alt_emu.find("label")
            if label_el is not None and label_el.text:
                return label_el.text.strip()
    except (ET.ParseError, OSError):
        pass

    return None


def get_active_core(system_name, rom_filename=None):
    """Resolve the active core for a system.

    Resolution chain:
    1. Per-system override (gamelist.xml alternativeEmulator)
    2. Live es_systems.xml default
    3. Static core_defaults.json fallback
    4. (None, None) if all fail

    Per-game override is Phase B scope -- not implemented here.

    Returns: (core_so_name, label) or (None, None).
    """
    es_systems = _load_es_systems()
    system_info = es_systems.get(system_name)

    # Try per-system override
    try:
        from lib import retrodeck_config
        retrodeck_home = retrodeck_config.get_retrodeck_home()
        if retrodeck_home:
            override_label = get_system_override(retrodeck_home, system_name)
            if override_label:
                # Resolve label to core_so using live es_systems data
                if system_info and override_label in system_info.get("label_to_core", {}):
                    core_so = system_info["label_to_core"][override_label]
                    return (core_so, override_label)
                # Try core_defaults fallback for label resolution
                defaults = _load_core_defaults()
                default_info = defaults.get(system_name, {})
                default_cores = default_info.get("cores", {})
                # cores is {core_so: label}, need reverse lookup
                for core_so, label in default_cores.items():
                    if label == override_label:
                        return (core_so, override_label)
    except Exception:
        pass

    # Use live es_systems.xml default
    if system_info and system_info.get("default_core"):
        return (system_info["default_core"], system_info["default_label"])

    # Fallback to core_defaults.json
    defaults = _load_core_defaults()
    default_info = defaults.get(system_name, {})
    if default_info.get("default_core"):
        return (default_info["default_core"], default_info.get("default_label"))

    return (None, None)
