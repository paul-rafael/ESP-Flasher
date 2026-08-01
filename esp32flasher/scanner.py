"""Findet flashbare Images in einem Projektordner."""

import glob
import json
import os
import re

MANIFEST_NAME = "flasher.json"

# S3/C3/C6/H2 booten ab 0x0, die klassischen ESP32 und der S2 ab 0x1000.
BOOTLOADER_OFFSET = {
    "esp32": "0x1000", "esp32s2": "0x1000",
    "esp32s3": "0x0", "esp32c3": "0x0", "esp32c6": "0x0", "esp32h2": "0x0",
}

# Dateien, die für sich genommen keine startfähige App sind.
NON_APP_NAMES = {"bootloader.bin", "partitions.bin", "boot_app0.bin",
                 "ota_data_initial.bin"}

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__",
             ".pio_libdeps", "libdeps", ".vscode", "dist", "build_pyinstaller"}

MAX_SCAN_DEPTH = 6
# Obergrenze, damit ein versehentlich gewähltes Riesenverzeichnis (etwa das
# Home-Verzeichnis) den Scan nicht minutenlang blockiert.
MAX_SCAN_ENTRIES = 20000


class FlashPlan:
    """Ein flashbarer Kandidat: parts = [(offset, pfad), ...] in Schreibreihenfolge."""

    KIND_RANK = {"manifest": 0, "merged": 1, "parts": 2, "arduino": 2, "single": 3}

    def __init__(self, kind, label, parts, chip="esp32", flash_size="4MB",
                 mtime=0.0, note=""):
        self.kind = kind
        self.label = label
        self.parts = parts
        self.chip = chip
        self.flash_size = flash_size
        self.mtime = mtime
        self.note = note

    @property
    def rank(self):
        return (self.KIND_RANK.get(self.kind, 9), -self.mtime)

    @property
    def missing(self):
        return [path for _offset, path in self.parts if not os.path.isfile(path)]

    def describe(self, base=None):
        return "\n".join(
            f"  {offset:>8}  {os.path.relpath(path, base) if base else path}"
            for offset, path in self.parts)


def guess_chip(*hints):
    """Chipvariante aus Env-/Boardnamen ableiten, etwa esp32dev -> esp32."""
    text = " ".join(hint.lower() for hint in hints if hint)
    for suffix in ("s3", "s2", "c3", "c6", "h2"):
        if f"esp32{suffix}" in text or f"esp32-{suffix}" in text:
            return f"esp32{suffix}"
    return "esp32"


def _board_from_platformio_ini(start_dir):
    """`board = ...` aus der nächstgelegenen platformio.ini oberhalb lesen."""
    directory = start_dir
    for _ in range(5):
        ini = os.path.join(directory, "platformio.ini")
        if os.path.isfile(ini):
            try:
                with open(ini, "r", errors="replace") as handle:
                    match = re.search(r"^\s*board\s*=\s*(\S+)", handle.read(), re.M)
                return match.group(1) if match else ""
            except OSError:
                return ""
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return ""


def _find_boot_app0(near_dir):
    """boot_app0.bin suchen: erst neben dem Build, dann im Arduino-Framework."""
    local = os.path.join(near_dir, "boot_app0.bin")
    if os.path.isfile(local):
        return local
    home = os.path.expanduser("~")
    for pattern in (
        os.path.join(home, ".platformio", "packages",
                     "framework-arduinoespressif32*", "tools", "partitions",
                     "boot_app0.bin"),
        os.path.join(home, ".platformio", "packages",
                     "framework-arduinoespressif32*", "tools", "boot_app0.bin"),
    ):
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def _walk_limited(root):
    """os.walk mit Tiefenlimit und Ausschlussliste; in .pio nur den build-Ordner."""
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.rstrip(os.sep).count(os.sep) - base_depth >= MAX_SCAN_DEPTH:
            dirnames[:] = []
            continue
        if os.path.basename(dirpath) == ".pio":
            dirnames[:] = [d for d in dirnames if d == "build"]
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".git")]
        yield dirpath, dirnames, filenames


def _manifest_part_path(manifest_path, entry_file):
    """Manifestpfad auflösen, begrenzt auf den Manifestordner.

    Ein Manifest stammt aus einem fremden Projekt. Ohne diese Grenze könnte ein
    Eintrag wie ../../../.ssh/id_rsa beliebige Dateien auf den Chip schreiben.
    """
    if os.path.isabs(entry_file) or entry_file.startswith("~"):
        return None
    base = os.path.realpath(os.path.dirname(manifest_path))
    candidate = os.path.realpath(os.path.join(base, entry_file))
    if candidate != base and not candidate.startswith(base + os.sep):
        return None
    return candidate


def _collect_files(folder):
    """-> (manifestpfade, [(ordner, dateiname)] aller .bin)"""
    manifests, binaries, seen = [], [], 0
    for dirpath, _dirnames, filenames in _walk_limited(folder):
        for name in filenames:
            seen += 1
            if seen > MAX_SCAN_ENTRIES:
                return manifests, binaries
            if name == MANIFEST_NAME:
                manifests.append(os.path.join(dirpath, name))
            elif name.lower().endswith(".bin"):
                binaries.append((dirpath, name))
    return manifests, binaries


def _plans_from_manifests(manifests, folder, used):
    plans = []
    for manifest in manifests:
        try:
            with open(manifest, "r") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        parts, rejected = [], False
        for entry in data.get("parts", []):
            if not isinstance(entry, dict) or "file" not in entry:
                rejected = True
                break
            path = _manifest_part_path(manifest, str(entry["file"]))
            if path is None:
                rejected = True
                break
            parts.append((str(entry.get("offset", "0x0")), path))
        if rejected or not parts:
            continue

        present = [p for _o, p in parts if os.path.isfile(p)]
        missing = [p for _o, p in parts if not os.path.isfile(p)]
        note = ("Fehlende Dateien: "
                + ", ".join(os.path.basename(m) for m in missing)) if missing else ""
        mtime = max((os.path.getmtime(p) for p in present),
                    default=os.path.getmtime(manifest))
        name = data.get("name") or os.path.relpath(manifest, folder)
        plans.append(FlashPlan("manifest", f"Manifest: {name}", parts,
                               chip=str(data.get("chip", "esp32")),
                               flash_size=str(data.get("flash_size", "4MB")),
                               mtime=mtime, note=note))
        used.update(p for _o, p in parts)
    return plans


def _plans_from_merged(binaries, folder, used):
    plans = []
    for dirpath, name in binaries:
        low = name.lower()
        if "merged" not in low and "factory" not in low:
            continue
        path = os.path.join(dirpath, name)
        if path in used:
            continue
        chip = guess_chip(os.path.relpath(dirpath, folder),
                          _board_from_platformio_ini(dirpath))
        plans.append(FlashPlan("merged", f"{name}  (komplettes Image @ 0x0)",
                               [("0x0", path)], chip=chip,
                               mtime=os.path.getmtime(path)))
        used.add(path)
    return plans


def _plans_from_build_dirs(by_dir, folder, used):
    """PlatformIO/ESP-IDF: bootloader + partitions + boot_app0 + app."""
    plans = []
    for dirpath, names in by_dir.items():
        lower = {n.lower() for n in names}
        app = next((n for n in names if n.lower() in ("firmware.bin", "app.bin")), None)
        if not app or "bootloader.bin" not in lower or "partitions.bin" not in lower:
            continue
        chip = guess_chip(os.path.basename(dirpath),
                          os.path.relpath(dirpath, folder),
                          _board_from_platformio_ini(dirpath))
        parts = [(BOOTLOADER_OFFSET.get(chip, "0x1000"),
                  os.path.join(dirpath, "bootloader.bin")),
                 ("0x8000", os.path.join(dirpath, "partitions.bin"))]
        boot_app0 = _find_boot_app0(dirpath)
        note = ""
        if boot_app0:
            parts.append(("0xe000", boot_app0))
        else:
            note = "boot_app0.bin nicht gefunden — nach 'Flash löschen' evtl. nötig"
        app_path = os.path.join(dirpath, app)
        parts.append(("0x10000", app_path))
        plans.append(FlashPlan(
            "parts", f"Build-Teile: {os.path.basename(dirpath)}  ({len(parts)} Dateien)",
            parts, chip=chip, mtime=os.path.getmtime(app_path), note=note))
        used.update(p for _o, p in parts)
    return plans


def _plans_from_arduino_export(by_dir, folder, used):
    """Arduino IDE: Sketch.ino.bin samt Begleitdateien."""
    plans = []
    for dirpath, names in by_dir.items():
        for name in names:
            if not name.lower().endswith(".ino.bin"):
                continue
            prefix = name[:-len(".bin")]
            boot = os.path.join(dirpath, prefix + ".bootloader.bin")
            part = os.path.join(dirpath, prefix + ".partitions.bin")
            app_path = os.path.join(dirpath, name)
            if app_path in used or not (os.path.isfile(boot) and os.path.isfile(part)):
                continue
            chip = guess_chip(os.path.relpath(dirpath, folder))
            parts = [(BOOTLOADER_OFFSET.get(chip, "0x1000"), boot),
                     ("0x8000", part)]
            boot_app0 = _find_boot_app0(dirpath)
            if boot_app0:
                parts.append(("0xe000", boot_app0))
            parts.append(("0x10000", app_path))
            plans.append(FlashPlan("arduino", f"Arduino-Export: {name}", parts,
                                   chip=chip, mtime=os.path.getmtime(app_path)))
            used.update(p for _o, p in parts)
    return plans


def _plans_from_single_bins(binaries, used):
    plans = []
    for dirpath, name in binaries:
        path = os.path.join(dirpath, name)
        low = name.lower()
        if (path in used or low in NON_APP_NAMES
                or "littlefs" in low or "spiffs" in low):
            continue
        plans.append(FlashPlan(
            "single", f"{name}  (nur App @ 0x10000)", [("0x10000", path)],
            mtime=os.path.getmtime(path),
            note="Bootloader/Partitionen müssen schon auf dem Chip sein."))
    return plans


def scan_project(folder):
    """Projektordner durchsuchen und die Kandidaten nach Güte sortiert liefern."""
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        return []

    manifests, binaries = _collect_files(folder)
    by_dir = {}
    for dirpath, name in binaries:
        by_dir.setdefault(dirpath, []).append(name)

    used = set()          # von einem besseren Plan bereits belegte Dateien
    plans = _plans_from_manifests(manifests, folder, used)
    plans += _plans_from_merged(binaries, folder, used)
    plans += _plans_from_build_dirs(by_dir, folder, used)
    plans += _plans_from_arduino_export(by_dir, folder, used)
    plans += _plans_from_single_bins(binaries, used)
    plans.sort(key=lambda plan: plan.rank)
    return plans
