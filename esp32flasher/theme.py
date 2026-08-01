"""Farbpaletten und Erkennung des Systemmodus."""

import os
import subprocess
import sys

THEMES = {
    "dark": {
        "bg":          "#171A1F",   # Fenster
        "surface":     "#1E2228",   # Karten
        "surface2":    "#272C34",   # Felder, sekundäre Flächen
        "hover":       "#2F353E",
        "border":      "#2B3038",
        "text":        "#D8DDE4",
        "dim":         "#98A0AC",
        "mute":        "#6E7784",
        "accent":      "#4A6FAE",
        "accent_hi":   "#567BBC",
        "on_accent":   "#FFFFFF",
        "ok":          "#6BA37E",
        "danger":      "#C8707A",
        "warn":        "#C2934F",
        "log_bg":      "#14171B",
        "log_fg":      "#C3C9D3",
        "disabled":    "#3A404A",
        "on_disabled": "#6E7784",
    },
    "light": {
        "bg":          "#F2F4F6",
        "surface":     "#FFFFFF",
        "surface2":    "#EBEEF1",
        "hover":       "#E1E5EA",
        "border":      "#DCE0E5",
        "text":        "#262A30",
        "dim":         "#5F6771",
        "mute":        "#8A929C",
        "accent":      "#315F9E",
        "accent_hi":   "#3B6BAC",
        "on_accent":   "#FFFFFF",
        "ok":          "#3F7D5C",
        "danger":      "#B0555F",
        "warn":        "#8E6B2E",
        "log_bg":      "#F7F8FA",
        "log_fg":      "#3A4048",
        "disabled":    "#E4E7EB",
        "on_disabled": "#A8AFB8",
    },
}

MONO = "SF Mono" if sys.platform == "darwin" else "Consolas"
SANS = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"


def detect_system_theme():
    """Systemeinstellung von macOS bzw. Windows lesen; im Zweifel dunkel."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2)
            # Der Schlüssel existiert nur im Dunkelmodus.
            return "dark" if "Dark" in result.stdout else "light"
        except (OSError, subprocess.SubprocessError):
            return "dark"
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                value, _type = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except (OSError, ImportError):
            return "dark"
    return "dark"


def palette(theme_mode):
    """Palette für auto | light | dark."""
    mode = detect_system_theme() if theme_mode == "auto" else theme_mode
    return THEMES.get(mode, THEMES["dark"])
