#!/usr/bin/env python3
"""ESP32 Flasher — Einstiegspunkt.

Oberfläche starten:   python3 flasher.py
Scanner ohne GUI:     python3 flasher.py --scan /pfad/zum/projekt

Die eigentliche Logik liegt im Paket ``esp32flasher``; siehe
docs/ARCHITEKTUR.md.
"""

import sys

from esp32flasher.scanner import scan_project


def print_scan(folder):
    plans = scan_project(folder)
    if not plans:
        print(f"Keine Kandidaten in {folder}")
        return 1
    for index, plan in enumerate(plans):
        marker = ">" if index == 0 else " "
        print(f"{marker} [{plan.kind}] {plan.label}   (chip={plan.chip})")
        print(plan.describe(folder))
        if plan.note:
            print(f"  {plan.note}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--scan" in argv:
        index = argv.index("--scan")
        if index + 1 >= len(argv):
            print("Aufruf: flasher.py --scan <projektordner>", file=sys.stderr)
            return 2
        return print_scan(argv[index + 1])

    from esp32flasher.ui.app import FlasherApp
    FlasherApp().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
