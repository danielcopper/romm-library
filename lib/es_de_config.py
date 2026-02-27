"""ES-DE configuration parser for active core resolution."""

import json
import os
import re

import decky  # for DECKY_USER_HOME and logging


# Module-level caches
_es_systems_cache = None  # dict or None
_core_defaults_cache = None  # dict or None

_CORE_SO_RE = re.compile(r"%CORE_RETROARCH%/([\w-]+_libretro)\.so")

_FLATPAK_SYSTEMS_DIR = "/var/lib/flatpak/app/net.retrodeck.retrodeck/current/active/files/retrodeck/components/es-de/share/es-de/resources/systems"

# Prefer linux/ (RetroDECK-customized, more complete), then unix/ as fallback.
_ES_SYSTEMS_CANDIDATES = [
    _FLATPAK_SYSTEMS_DIR + "/linux/es_systems.xml",
    _FLATPAK_SYSTEMS_DIR + "/unix/es_systems.xml",
]


def _reset_cache():
    """Reset caches (for testing)."""
    global _es_systems_cache, _core_defaults_cache
    _es_systems_cache = None
    _core_defaults_cache = None


def find_es_systems_xml():
    """Locate es_systems.xml inside the RetroDECK flatpak installation.

    Uses the flatpak 'active' symlink to find the current version.
    Searches linux/ first (RetroDECK-customized), then unix/ as fallback.
    Works on SteamOS, Bazzite, and other Linux distros with flatpak.

    Returns the path or None.
    """
    for path in _ES_SYSTEMS_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


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


def get_available_cores(system_name):
    """Return available RetroArch cores for a system.

    Merges live es_systems.xml data with core_defaults.json fallback.
    Returns: [{"core_so": str, "label": str, "is_default": bool}, ...]
    Empty list if system is unknown.
    """
    es_systems = _load_es_systems()
    system_info = es_systems.get(system_name)

    if system_info and system_info.get("cores"):
        default_core = system_info.get("default_core")
        cores = [
            {"core_so": core_so, "label": label, "is_default": core_so == default_core}
            for core_so, label in system_info["cores"].items()
        ]
        decky.logger.debug("es_de_config: get_available_cores(%s) -> %d cores from es_systems.xml", system_name, len(cores))
        return cores

    # Fallback to core_defaults.json
    defaults = _load_core_defaults()
    default_info = defaults.get(system_name, {})
    if default_info.get("cores"):
        default_core = default_info.get("default_core")
        cores = [
            {"core_so": core_so, "label": label, "is_default": core_so == default_core}
            for core_so, label in default_info["cores"].items()
        ]
        decky.logger.debug("es_de_config: get_available_cores(%s) -> %d cores from core_defaults.json (fallback)", system_name, len(cores))
        return cores

    decky.logger.debug("es_de_config: get_available_cores(%s) -> no cores found", system_name)
    return []


def _gamelist_path(retrodeck_home, system_name):
    """Return the gamelist.xml path for a system."""
    return os.path.join(retrodeck_home, "ES-DE", "gamelists", system_name, "gamelist.xml")


def _read_gamelist_raw(path):
    """Read gamelist.xml and return raw bytes, or None if not found."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _write_gamelist_atomic(path, content):
    """Write gamelist.xml content atomically via tmp file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(content)
    os.replace(tmp_path, path)


def _parse_gamelist_preserving(data):
    """Parse gamelist.xml into a structured representation that can be modified and reconstructed.

    Returns: {
        "alt_emulator_label": str | None,
        "games": [{
            "path": str,         # <path> value
            "altemulator": str | None,  # <altemulator> value
            "raw_xml": str,      # full <game>...</game> XML
        }],
        "other_content": str,    # any non-game, non-altEmulator content
    } or None on parse failure.
    """
    try:
        from xml.parsers import expat
    except ImportError:
        return None

    result = {
        "alt_emulator_label": None,
        "games": [],
    }
    state = {
        "path": [],
        "text": "",
        "in_game": False,
        "game_depth": 0,
        "game_xml_parts": [],
        "game_path": None,
        "game_altemulator": None,
        "game_tag_name": None,
    }

    def start_element(name, attrs):
        state["path"].append(name)
        state["text"] = ""

        if name == "game" and state["path"] == ["gameList", "game"]:
            state["in_game"] = True
            state["game_depth"] = len(state["path"])
            state["game_xml_parts"] = []
            state["game_path"] = None
            state["game_altemulator"] = None
            # Build opening tag
            attr_str = ""
            for k, v in attrs.items():
                attr_str += f' {k}="{_escape_xml(v)}"'
            state["game_xml_parts"].append(f"<game{attr_str}>")
        elif state["in_game"]:
            attr_str = ""
            for k, v in attrs.items():
                attr_str += f' {k}="{_escape_xml(v)}"'
            state["game_xml_parts"].append(f"<{name}{attr_str}>")

    def end_element(name):
        text = state["text"].strip()

        if state["in_game"]:
            if name == "game" and len(state["path"]) == state["game_depth"]:
                # Close game element
                state["game_xml_parts"].append("</game>")
                result["games"].append({
                    "path": state["game_path"],
                    "altemulator": state["game_altemulator"],
                    "raw_xml": "".join(state["game_xml_parts"]),
                })
                state["in_game"] = False
            else:
                # Inside game: capture text and closing tag
                if state["text"]:
                    state["game_xml_parts"].append(_escape_xml(state["text"]))
                state["game_xml_parts"].append(f"</{name}>")
                # Track specific child elements
                if name == "path":
                    state["game_path"] = text
                elif name == "altemulator":
                    state["game_altemulator"] = text
        else:
            # Outside game: look for alternativeEmulator/label
            if (len(state["path"]) >= 2
                    and state["path"][-1] == "label"
                    and state["path"][-2] == "alternativeEmulator"
                    and text):
                result["alt_emulator_label"] = text

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

    return result


def _escape_xml(text):
    """Escape special XML characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _reconstruct_gamelist(alt_label, games_xml_list):
    """Reconstruct gamelist.xml from components.

    alt_label: the alternativeEmulator label, or None to omit
    games_xml_list: list of raw <game>...</game> XML strings
    """
    parts = ['<?xml version="1.0"?>\n<gameList>']
    if alt_label:
        parts.append(f"\n  <alternativeEmulator>\n    <label>{_escape_xml(alt_label)}</label>\n  </alternativeEmulator>")
    for game_xml in games_xml_list:
        parts.append(f"\n  {game_xml}")
    parts.append("\n</gameList>\n")
    return "".join(parts)


def set_system_override(retrodeck_home, system_name, core_label):
    """Set or clear the system-wide core override in gamelist.xml.

    Writes <alternativeEmulator><label>X</label></alternativeEmulator>.
    If core_label is None or empty, removes the alternativeEmulator element.
    Preserves all existing <game> entries.
    Creates file/directories if they don't exist.
    """
    path = _gamelist_path(retrodeck_home, system_name)
    raw = _read_gamelist_raw(path)

    if raw:
        parsed = _parse_gamelist_preserving(raw)
        if parsed is None:
            decky.logger.warning("es_de_config: failed to parse %s for writing", path)
            return False
        games_xml = [g["raw_xml"] for g in parsed["games"]]
    else:
        games_xml = []

    content = _reconstruct_gamelist(core_label or None, games_xml)
    _write_gamelist_atomic(path, content)
    action = "cleared" if not core_label else f"set to '{core_label}'"
    decky.logger.info("es_de_config: system override for %s %s (%s)", system_name, action, path)
    return True


def set_game_override(retrodeck_home, system_name, rom_path, core_label):
    """Set or clear per-game core override in gamelist.xml.

    rom_path: the relative path for the game (e.g. "./Pokemon.gba")
    If core_label is None/empty, removes the altemulator from the game entry.
    Creates game entry if not found. Preserves all other content.
    """
    path = _gamelist_path(retrodeck_home, system_name)
    raw = _read_gamelist_raw(path)

    if raw:
        parsed = _parse_gamelist_preserving(raw)
        if parsed is None:
            decky.logger.warning("es_de_config: failed to parse %s for writing", path)
            return False
        alt_label = parsed["alt_emulator_label"]
        games = parsed["games"]
    else:
        alt_label = None
        games = []

    # Find or create the game entry
    found = False
    new_games_xml = []
    for game in games:
        if game["path"] == rom_path:
            found = True
            # Rebuild this game entry with updated altemulator
            new_games_xml.append(_rebuild_game_xml(game["raw_xml"], core_label))
        else:
            new_games_xml.append(game["raw_xml"])

    if not found:
        # Create new game entry
        if core_label:
            escaped_path = _escape_xml(rom_path)
            escaped_label = _escape_xml(core_label)
            new_games_xml.append(
                f"<game>\n    <path>{escaped_path}</path>\n    <altemulator>{escaped_label}</altemulator>\n  </game>"
            )

    content = _reconstruct_gamelist(alt_label, new_games_xml)
    _write_gamelist_atomic(path, content)
    action = "cleared" if not core_label else f"set to '{core_label}'"
    decky.logger.info("es_de_config: game override for %s [%s] %s (%s)", system_name, rom_path, action, path)
    return True


def _rebuild_game_xml(raw_xml, core_label):
    """Rebuild a <game> XML string with updated <altemulator> value.

    If core_label is None/empty, removes <altemulator> entirely.
    Preserves all other child elements.
    """
    try:
        from xml.parsers import expat
    except ImportError:
        return raw_xml

    elements = []  # list of (type, data) tuples
    state = {"path": [], "text": "", "skip_altemulator": False}

    def start_element(name, attrs):
        state["path"].append(name)
        state["text"] = ""
        if name == "altemulator":
            state["skip_altemulator"] = True
            return
        if state["skip_altemulator"]:
            return
        if name == "game":
            return  # skip root game tag, we add it ourselves
        attr_str = ""
        for k, v in attrs.items():
            attr_str += f' {k}="{_escape_xml(v)}"'
        elements.append(("open", f"<{name}{attr_str}>"))

    def end_element(name):
        if name == "altemulator":
            state["skip_altemulator"] = False
            state["path"].pop()
            state["text"] = ""
            return
        if state["skip_altemulator"]:
            state["path"].pop()
            state["text"] = ""
            return
        if name == "game" and len(state["path"]) == 1:
            state["path"].pop()
            state["text"] = ""
            return  # skip root close
        if state["text"]:
            elements.append(("text", _escape_xml(state["text"])))
        elements.append(("close", f"</{name}>"))
        state["path"].pop()
        state["text"] = ""

    def char_data(data):
        if not state["skip_altemulator"]:
            state["text"] += data

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = char_data

    try:
        parser.Parse(raw_xml.encode("utf-8"), True)
    except expat.ExpatError:
        return raw_xml  # fallback: return unchanged

    # Reconstruct
    parts = ["<game>"]
    for _, data in elements:
        parts.append(data)
    if core_label:
        parts.append(f"<altemulator>{_escape_xml(core_label)}</altemulator>")
    parts.append("</game>")
    return "".join(parts)
