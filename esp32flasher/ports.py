"""Serielle Ports finden, Adapter erkennen, blockierte Ports freigeben."""

import os
import signal
import subprocess

try:
    import serial.tools.list_ports
except ImportError:
    serial = None

# PID None = alle Geräte dieses Herstellers.
KNOWN_USB = [
    (0x10C4, 0xEA60, "CP210x"),        # Silicon Labs CP2102/CP2104
    (0x1A86, 0x7523, "CH340"),
    (0x1A86, 0x55D4, "CH9102"),
    (0x0403, None,   "FTDI"),
    (0x067B, None,   "Prolific"),
    (0x303A, None,   "Espressif USB"),  # natives USB (S2/S3/C3 …)
]

# Ersatzerkennung, wenn die VID/PID nicht in der Liste steht.
ADAPTER_KEYWORDS = ("cp210", "ch340", "ch341", "ch910", "ftdi", "espressif",
                    "silicon labs", "wch", "usb serial", "uart bridge")


def list_ports():
    """Serielle Ports ohne Bluetooth-/Debug-Geräte."""
    if serial is None:
        return []
    return [port for port in serial.tools.list_ports.comports()
            if "bluetooth" not in (port.description or "").lower()
            and "bluetooth" not in port.device.lower()
            and "debug" not in port.device.lower()]


def adapter_name(port_info):
    """Name des erkannten USB-UART-Adapters, sonst None."""
    if port_info is None:
        return None
    if port_info.vid is not None:
        for vid, pid, name in KNOWN_USB:
            if port_info.vid == vid and (pid is None or port_info.pid == pid):
                return name
    text = f"{port_info.description or ''} {port_info.manufacturer or ''}".lower()
    for keyword in ADAPTER_KEYWORDS:
        if keyword in text:
            return port_info.description or keyword
    return None


def find_port_owner(port):
    """(pid, name) des Prozesses, der den Port belegt, sonst (None, None).

    Nutzt lsof — unter Windows gibt es dafür kein Bordmittel.
    """
    if os.name == "nt":
        return None, None
    try:
        output = subprocess.check_output(["lsof", "--", port], text=True,
                                         stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None, None
    for line in output.splitlines()[1:]:      # Kopfzeile überspringen
        fields = line.split()
        if len(fields) >= 2 and fields[1].isdigit():
            return int(fields[1]), fields[0]
    return None, None


def release_port(port):
    """Den Prozess beenden, der den Port hält. -> (erfolg, meldung)

    SIGTERM statt SIGKILL, damit der Prozess den Port sauber schließen kann.
    """
    pid, name = find_port_owner(port)
    if pid is None:
        return False, "Kein blockierender Prozess gefunden."
    if pid in (0, 1) or pid == os.getpid():
        return False, f"Prozess {pid} wird aus Sicherheitsgründen nicht beendet."
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as error:
        return False, f"Konnte PID {pid} nicht beenden: {error}"
    return True, f"Prozess '{name}' (PID {pid}) beendet."
