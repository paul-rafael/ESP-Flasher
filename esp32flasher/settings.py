"""Einstellungen laden und speichern.

Beim Lesen wird validiert: ein halb geschriebener oder vertippter Wert darf die
App nicht beim Start umbringen.
"""

import json
import os
import sys

APP_DIR_NAME = "ESP32Flasher"
LEGACY_DIR_NAME = "ESP32UniversalFlasher"

FLASH_BAUDS = ["115200", "230400", "460800", "921600"]
MONITOR_BAUDS = ["9600", "115200", "921600"]
ADDR_PRESETS = ["0x10000", "0x0"]

DEFAULTS = {
    "port": "",
    "baud": "921600",
    "mode": "project",
    "project": "",
    "recent": [],
    "firmware": "",
    "addr": "0x10000",
    "mon_baud": "115200",
    "no_autoreset": False,
    "theme": "auto",
}


def _config_dir(name):
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, name)


def settings_path():
    return os.path.join(_config_dir(APP_DIR_NAME), "settings.json")


def _legacy_path():
    return os.path.join(_config_dir(LEGACY_DIR_NAME), "settings.json")


def _is_hex_offset(value):
    try:
        int(value, 16)
        return True
    except (TypeError, ValueError):
        return False


def _clean(raw):
    """Rohdaten auf gültige Werte zurechtstutzen; Unbekanntes fällt weg."""
    result = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return result

    for key in ("port", "project", "firmware"):
        value = raw.get(key)
        if isinstance(value, str):
            result[key] = value

    if raw.get("baud") in FLASH_BAUDS:
        result["baud"] = raw["baud"]
    if raw.get("mon_baud") in MONITOR_BAUDS:
        result["mon_baud"] = raw["mon_baud"]
    if raw.get("mode") in ("project", "bin"):
        result["mode"] = raw["mode"]
    if raw.get("theme") in ("auto", "light", "dark"):
        result["theme"] = raw["theme"]
    if _is_hex_offset(raw.get("addr")):
        result["addr"] = raw["addr"]

    result["no_autoreset"] = bool(raw.get("no_autoreset", False))

    recent = raw.get("recent")
    if isinstance(recent, list):
        result["recent"] = [p for p in recent
                            if isinstance(p, str) and os.path.isdir(p)][:8]
    return result


def load():
    """Einstellungen lesen; bei fehlender oder kaputter Datei die Vorgaben."""
    path = settings_path()
    if not os.path.exists(path) and os.path.exists(_legacy_path()):
        path = _legacy_path()          # Umzug vom alten Ordnernamen
    try:
        with open(path, "r") as handle:
            return _clean(json.load(handle))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(values):
    """Schreiben. Fehler werden geschluckt: ein nicht beschreibbares Profil darf
    das Beenden nicht blockieren."""
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            json.dump(_clean(values), handle, indent=2)
    except OSError:
        pass
