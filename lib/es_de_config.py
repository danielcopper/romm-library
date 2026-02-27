"""ES-DE configuration parser for active core resolution."""

import glob
import json
import os
import re

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

    Uses xml.parsers.expat (SAX-style) instead of xml.etree.ElementTree
    because Decky's PyInstaller-frozen Python does not bundle xml.etree.

    Returns: {system_name: {
        "default_core": str | None,
        "default_label": str | None,
        "cores": {core_so: label},
        "label_to_core": {label: core_so},
    }}

    Returns empty dict if file can't be parsed or fails structural validation.
    """
    try:
        from xml.parsers import expat
    except ImportError:
        decky.logger.warning("es_de_config: xml.parsers.expat not available")
        return {}

    try:
        with open(xml_path, "rb") as f:
            data = f.read()
    except OSError as e:
        decky.logger.warning("es_de_config: failed to read %s: %s", xml_path, e)
        return {}

    systems = {}
    state = {
        "path": [],       # element name stack
        "text": "",       # accumulated character data
        "root_tag": None,
        "current_system": None,
        "current_label": "",
    }

    def start_element(name, attrs):
        state["path"].append(name)
        state["text"] = ""
        if state["root_tag"] is None:
            state["root_tag"] = name
        if name == "system":
            state["current_system"] = {
                "name": None,
                "default_core": None,
                "default_label": None,
                "cores": {},
                "label_to_core": {},
            }
        elif name == "command":
            state["current_label"] = attrs.get("label", "")

    def end_element(name):
        text = state["text"].strip()
        path = state["path"]
        sys = state["current_system"]

        if path == ["systemList", "system", "name"] and sys is not None:
            sys["name"] = text
        elif path == ["systemList", "system", "command"] and sys is not None:
            match = _CORE_SO_RE.search(text)
            if match:
                core_so = match.group(1)
                label = state["current_label"]
                sys["cores"][core_so] = label
                sys["label_to_core"][label] = core_so
                if sys["default_core"] is None:
                    sys["default_core"] = core_so
                    sys["default_label"] = label
        elif name == "system" and sys is not None:
            if sys["name"]:
                systems[sys["name"]] = {
                    "default_core": sys["default_core"],
                    "default_label": sys["default_label"],
                    "cores": sys["cores"],
                    "label_to_core": sys["label_to_core"],
                }
            state["current_system"] = None

        state["path"].pop()
        state["text"] = ""

    def char_data(data):
        state["text"] += data

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = char_data

    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        decky.logger.warning("es_de_config: failed to parse %s: %s", xml_path, e)
        return {}

    if state["root_tag"] != "systemList":
        decky.logger.warning(
            "es_de_config: unexpected root tag '%s' (expected 'systemList')",
            state["root_tag"],
        )
        return {}

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
        from xml.parsers import expat
    except ImportError:
        return None

    try:
        with open(gamelist_path, "rb") as f:
            data = f.read()
    except OSError:
        return None

    result = {"label": None}
    state = {"path": [], "text": ""}

    def start_element(name, attrs):
        state["path"].append(name)
        state["text"] = ""

    def end_element(name):
        text = state["text"].strip()
        if (len(state["path"]) >= 2
                and state["path"][-1] == "label"
                and state["path"][-2] == "alternativeEmulator"
                and text):
            result["label"] = text
        state["path"].pop()
        state["text"] = ""

    def char_data(data):
        state["text"] += data

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = char_data

    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        return None

    return result["label"]


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
