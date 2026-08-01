"""Das Fenster: Bedienung, Zustand und Anbindung der Kernmodule.

Hintergrund-Threads fassen niemals Widgets an, sondern schicken Nachrichten in
self.queue. _drain_queue() leert sie im Tk-Thread — der einzige Ort, an dem
sich die Oberfläche ändert.
"""

import os
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
except ImportError:
    serial = None

from .. import esptool_runner, ports, settings
from ..scanner import scan_project
from ..theme import MONO, SANS, palette
from .widgets import Widgets

WINDOW_TITLE = "ESP32 Flasher"
MAX_LOG_LINES = 400
MONITOR_READ_TIMEOUT = 0.2
BOOT_CHECK_SECONDS = 15


class FlasherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("720x960")
        self.minsize(660, 800)

        self.queue = queue.Queue()
        self.busy = False
        self.plans = []
        self.recent_projects = []
        self.log_entries = []          # [(text, tag)], überlebt den Themewechsel
        self.active_tab = "Log"
        self.port_infos = {}
        self._last_line_was_progress = False

        self.monitor_thread = None
        self.monitor_stop = threading.Event()
        self._serial = None
        self._serial_lock = threading.Lock()

        self._create_variables()
        stored = settings.load()
        self._apply_settings(stored)
        self.theme_mode = stored["theme"]
        self.widgets = Widgets(palette(self.theme_mode))

        self._build_ui()
        self._restore_lists()
        self.refresh_ports()
        if self.project_var.get():
            self.scan_folder(log_result=False)

        self.after(60, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if serial is None or esptool_runner.esptool is None:
            self.log("esptool/pyserial fehlen — pip install -r requirements.txt",
                     "err")

    def _create_variables(self):
        """Einmalig anlegen: sie überleben den Neuaufbau beim Themewechsel,
        die Widgets nicht."""
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar()
        self.port_hint_var = tk.StringVar()
        self.no_autoreset_var = tk.BooleanVar()
        self.mode_var = tk.StringVar()
        self.project_var = tk.StringVar()
        self.plan_var = tk.StringVar()
        self.plan_info_var = tk.StringVar()
        self.firmware_var = tk.StringVar()
        self.addr_var = tk.StringVar()
        self.monitor_baud_var = tk.StringVar()
        self.autoscroll_var = tk.BooleanVar(value=True)
        self.send_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Bereit")

    def _apply_settings(self, values):
        self.port_var.set(values["port"])
        self.baud_var.set(values["baud"])
        self.mode_var.set(values["mode"])
        self.project_var.set(values["project"])
        self.firmware_var.set(values["firmware"])
        self.addr_var.set(values["addr"])
        self.monitor_baud_var.set(values["mon_baud"])
        self.no_autoreset_var.set(values["no_autoreset"])
        self.recent_projects = list(values["recent"])

    def _collect_settings(self):
        return {
            "port": self.port_var.get(),
            "baud": self.baud_var.get(),
            "mode": self.mode_var.get(),
            "project": self.project_var.get(),
            "recent": self.recent_projects,
            "firmware": self.firmware_var.get(),
            "addr": self.addr_var.get(),
            "mon_baud": self.monitor_baud_var.get(),
            "no_autoreset": self.no_autoreset_var.get(),
            "theme": self.theme_mode,
        }

    def set_theme(self, mode):
        if mode == self.theme_mode:
            return
        self.theme_mode = mode
        self.widgets = Widgets(palette(mode))
        self._rebuild_ui()
        settings.save(self._collect_settings())

    def _rebuild_ui(self):
        """Komplett neu aufbauen — zuverlässiger, als jedes Widget einzeln
        umzufärben, und ein Themewechsel ist selten."""
        monitor_text = self.monitor_text.get("1.0", "end-1c")
        monitoring = self._monitor_running()
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self._restore_lists()
        self._render_log()
        if monitor_text.strip():
            self._append_monitor(monitor_text)
        self._update_port_hint()
        self._show_plan()
        if monitoring:
            self.monitor_button.config(text="Stop")
        if self.busy:
            self._set_actions_enabled(False)

    def _restore_lists(self):
        self.port_combo["values"] = list(self.port_infos)
        self.plan_combo["values"] = [plan.label for plan in self.plans]
        self.project_combo["values"] = self.recent_projects

    def _build_ui(self):
        color = self.widgets.c
        widgets = self.widgets
        widgets.apply_ttk_style(self)
        pad = 20

        header = tk.Frame(self, bg=color["bg"])
        header.pack(fill="x", padx=pad, pady=(20, 16))
        tk.Label(header, text=WINDOW_TITLE, bg=color["bg"], fg=color["text"],
                 font=(SANS, 16, "bold")).pack(side="left")
        widgets.segmented(
            header, (("auto", "Auto"), ("light", "Hell"), ("dark", "Dunkel")),
            self.theme_mode, self.set_theme).pack(side="right")

        # Vor den expandierenden Panels packen, sonst drängen sie die
        # Statuszeile aus dem Fenster.
        status = tk.Frame(self, bg=color["bg"])
        status.pack(fill="x", side="bottom")
        tk.Frame(status, bg=color["border"], height=1).pack(fill="x")
        tk.Label(status, textvariable=self.status_var, anchor="w", bg=color["bg"],
                 fg=color["mute"], font=(SANS, 10)).pack(fill="x", padx=pad, pady=7)

        self._build_connection_card(pad)
        self._build_firmware_card(pad)
        self._build_actions(pad)
        self._build_console(pad)
        self._update_mode()

    def _build_connection_card(self, pad):
        widgets, color = self.widgets, self.widgets.c
        outer, body = widgets.card(self, "Verbindung")
        outer.pack(fill="x", padx=pad, pady=(0, 12))

        row = tk.Frame(body, bg=color["surface"])
        row.pack(fill="x")
        widgets.label(row, "Port", "dim", 10).pack(side="left")
        self.port_combo = ttk.Combobox(row, textvariable=self.port_var,
                                       state="readonly", font=(SANS, 11))
        self.port_combo.pack(side="left", fill="x", expand=True, padx=(10, 8))
        self.port_combo.bind("<<ComboboxSelected>>",
                             lambda _e: self._update_port_hint())
        widgets.button(row, "Aktualisieren", self.refresh_ports, small=True).pack(
            side="left", padx=(0, 16))
        widgets.label(row, "Baud", "dim", 10).pack(side="left")
        ttk.Combobox(row, textvariable=self.baud_var, values=settings.FLASH_BAUDS,
                     width=8, state="readonly", font=(SANS, 11)).pack(
            side="left", padx=(10, 0))

        hint_row = tk.Frame(body, bg=color["surface"])
        hint_row.pack(fill="x", pady=(11, 0))
        self.port_dot = tk.Canvas(hint_row, width=9, height=9, bg=color["surface"],
                                  highlightthickness=0)
        self._dot = self.port_dot.create_oval(1, 1, 8, 8, fill=color["mute"],
                                              outline="")
        self.port_dot.pack(side="left", pady=(1, 0))
        self.port_hint = tk.Label(hint_row, textvariable=self.port_hint_var,
                                  bg=color["surface"], fg=color["dim"],
                                  font=(SANS, 10))
        self.port_hint.pack(side="left", padx=(7, 0))
        self.release_button = widgets.link(hint_row, "Port freigeben",
                                           self.release_port)
        self.release_button.pack(side="right")

        widgets.check(body, "Ohne Auto-Reset", self.no_autoreset_var).pack(
            fill="x", pady=(9, 0))

    def _build_firmware_card(self, pad):
        widgets, color = self.widgets, self.widgets.c
        outer, body = widgets.card(self, "Firmware")
        outer.pack(fill="x", padx=pad, pady=(0, 12))

        widgets.radio(body, "Projektordner", self.mode_var, "project",
                      self._update_mode).pack(fill="x")

        project_row = tk.Frame(body, bg=color["surface"])
        project_row.pack(fill="x", padx=(22, 0), pady=(6, 0))
        self.project_combo = ttk.Combobox(project_row, textvariable=self.project_var,
                                          font=(SANS, 11))
        self.project_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.project_combo.bind("<<ComboboxSelected>>", lambda _e: self.scan_folder())
        self.project_button = widgets.button(project_row, "Wählen",
                                             self.browse_project, small=True)
        self.project_button.pack(side="left")

        plan_row = tk.Frame(body, bg=color["surface"])
        plan_row.pack(fill="x", padx=(22, 0), pady=(6, 0))
        self.plan_combo = ttk.Combobox(plan_row, textvariable=self.plan_var,
                                       state="readonly", font=(SANS, 11))
        self.plan_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.plan_combo.bind("<<ComboboxSelected>>", lambda _e: self._show_plan())
        self.scan_button = widgets.button(plan_row, "Scan", self.scan_folder,
                                          small=True)
        self.scan_button.pack(side="left")

        tk.Label(body, textvariable=self.plan_info_var, bg=color["surface"],
                 fg=color["mute"], font=(MONO, 9), justify="left",
                 anchor="w").pack(fill="x", padx=(22, 0), pady=(8, 0))

        widgets.separator(body).pack(fill="x", pady=13)

        widgets.radio(body, "Einzelne .bin-Datei", self.mode_var, "bin",
                      self._update_mode).pack(fill="x")
        file_row = tk.Frame(body, bg=color["surface"])
        file_row.pack(fill="x", padx=(22, 0), pady=(6, 0))
        self.firmware_entry = widgets.entry(file_row, self.firmware_var)
        self.firmware_entry.pack(side="left", fill="x", expand=True, ipady=5,
                                 padx=(0, 8))
        self.firmware_button = widgets.button(file_row, "Wählen",
                                              self.browse_firmware, small=True)
        self.firmware_button.pack(side="left", padx=(0, 16))
        widgets.label(file_row, "Adresse", "dim", 10).pack(side="left")
        self.addr_combo = ttk.Combobox(file_row, textvariable=self.addr_var,
                                       values=settings.ADDR_PRESETS, width=9,
                                       font=(SANS, 11))
        self.addr_combo.pack(side="left", padx=(10, 0))

    def _build_actions(self, pad):
        widgets, color = self.widgets, self.widgets.c

        primary = tk.Frame(self, bg=color["bg"])
        primary.pack(fill="x", padx=pad, pady=(0, 8))
        self.flash_button = widgets.button(primary, "Firmware flashen",
                                           self.flash_firmware, kind="primary")
        self.flash_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.erase_button = widgets.button(primary, "Flash löschen",
                                           self.erase_flash, kind="danger")
        self.erase_button.pack(side="left", fill="x", expand=True)

        secondary = tk.Frame(self, bg=color["bg"])
        secondary.pack(fill="x", padx=pad, pady=(0, 10))
        self.check_button = widgets.button(secondary, "Gerät prüfen",
                                           self.check_device, small=True)
        self.boot_check_button = widgets.button(secondary, "Boot-Check",
                                                self.boot_check, small=True)
        self.reset_button = widgets.button(secondary, "Reset", self.reset_board,
                                           small=True)
        self.export_button = widgets.button(secondary, "Exportieren",
                                            self.export_merged, small=True)
        for button in (self.check_button, self.boot_check_button,
                       self.reset_button, self.export_button):
            gap = (0, 8) if button is not self.export_button else 0
            button.pack(side="left", fill="x", expand=True, padx=gap)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100,
                                        style="Flash.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=pad, pady=(0, 12))

    def _build_console(self, pad):
        """Log und Monitor teilen sich ein Panel — zwei Panels passten nicht
        ins Fenster."""
        widgets, color = self.widgets, self.widgets.c
        panel = tk.Frame(self, bg=color["surface"],
                         highlightbackground=color["border"],
                         highlightcolor=color["border"], highlightthickness=1)
        panel.pack(fill="both", expand=True, padx=pad, pady=(0, 12))

        tab_bar = tk.Frame(panel, bg=color["surface"])
        tab_bar.pack(fill="x", padx=18, pady=(13, 9))
        self.tab_labels = {}
        for name in ("Log", "Monitor"):
            label = tk.Label(tab_bar, text=" ".join(name.upper()),
                             bg=color["surface"], fg=color["mute"],
                             font=(SANS, 9), cursor="hand2")
            label.bind("<Button-1>", lambda _e, n=name: self.show_tab(n))
            label.pack(side="left", padx=(0, 20))
            self.tab_labels[name] = label

        self.tab_body = tk.Frame(panel, bg=color["surface"])
        self.tab_body.pack(fill="both", expand=True, padx=18, pady=(0, 15))

        self.log_pane = tk.Frame(self.tab_body, bg=color["surface"])
        self.log_text = widgets.console(self.log_pane, height=8)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(self.log_pane, command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_scroll.set, state="disabled")
        for tag, tone in (("ok", "ok"), ("err", "danger"), ("warn", "warn"),
                          ("cmd", "accent"), ("dim", "mute")):
            self.log_text.tag_config(tag, foreground=color[tone])

        self.monitor_pane = tk.Frame(self.tab_body, bg=color["surface"])
        bar = tk.Frame(self.monitor_pane, bg=color["surface"])
        bar.pack(fill="x", pady=(0, 9))
        widgets.label(bar, "Baud", "dim", 10).pack(side="left")
        ttk.Combobox(bar, textvariable=self.monitor_baud_var,
                     values=settings.MONITOR_BAUDS, width=8, state="readonly",
                     font=(SANS, 11)).pack(side="left", padx=(10, 10))
        self.monitor_button = widgets.button(bar, "Start", self.toggle_monitor,
                                             small=True)
        self.monitor_button.pack(side="left", padx=(0, 8))
        widgets.button(bar, "Leeren", self.clear_monitor, small=True).pack(
            side="left")
        widgets.check(bar, "Auto-Scroll", self.autoscroll_var).pack(
            side="left", padx=14)

        send_row = tk.Frame(self.monitor_pane, bg=color["surface"])
        send_row.pack(fill="x", side="bottom", pady=(9, 0))
        send_entry = widgets.entry(send_row, self.send_var)
        send_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
        send_entry.bind("<Return>", lambda _e: self.send_serial())
        widgets.button(send_row, "Senden", self.send_serial, small=True).pack(
            side="left")

        monitor_body = tk.Frame(self.monitor_pane, bg=color["surface"])
        monitor_body.pack(fill="both", expand=True)
        self.monitor_text = widgets.console(monitor_body, height=8)
        self.monitor_text.pack(side="left", fill="both", expand=True)
        monitor_scroll = ttk.Scrollbar(monitor_body,
                                       command=self.monitor_text.yview)
        monitor_scroll.pack(side="right", fill="y")
        self.monitor_text.config(yscrollcommand=monitor_scroll.set,
                                 state="disabled")

        self.show_tab(self.active_tab)

    def show_tab(self, name):
        self.active_tab = name
        for key, label in self.tab_labels.items():
            label.config(fg=self.widgets.c["text"] if key == name
                         else self.widgets.c["mute"])
        self.log_pane.pack_forget()
        self.monitor_pane.pack_forget()
        pane = self.log_pane if name == "Log" else self.monitor_pane
        pane.pack(fill="both", expand=True)

    def _update_mode(self):
        project = self.mode_var.get() == "project"
        self.project_combo.config(state="normal" if project else "disabled")
        self.plan_combo.config(state="readonly" if project else "disabled")
        self.firmware_entry.config(state="disabled" if project else "normal")
        self.addr_combo.config(state="disabled" if project else "normal")
        for button, active in ((self.project_button, project),
                               (self.scan_button, project),
                               (self.firmware_button, not project)):
            self.widgets.set_enabled(button, active)

    def refresh_ports(self):
        found = ports.list_ports()
        self.port_infos = {port.device: port for port in found}
        devices = list(self.port_infos)
        self.port_combo["values"] = devices

        # Nur eingreifen, wenn die bisherige Wahl weg ist — eine bewusst
        # gewählte Schnittstelle darf ein Refresh nicht stillschweigend ersetzen.
        if self.port_var.get() not in devices:
            preferred = next(
                (d for d in devices if ports.adapter_name(self.port_infos[d])), None)
            self.port_var.set(preferred or (devices[0] if devices else ""))

        if devices:
            self.log(f"{len(devices)} Port(s): " + ", ".join(
                f"{d} ({self.port_infos[d].description})" for d in devices))
        else:
            self.log("Keine seriellen Ports gefunden.", "warn")
        self._update_port_hint()

    def _update_port_hint(self):
        info = self.port_infos.get(self.port_var.get())
        name = ports.adapter_name(info)
        if name:
            self.port_hint_var.set(f"{name} erkannt")
            tone = "ok"
        elif info:
            self.port_hint_var.set("Kein bekannter ESP32-Adapter")
            tone = "warn"
        else:
            self.port_hint_var.set("Kein Port")
            tone = "mute"
        self.port_hint.config(fg=self.widgets.c["dim" if tone == "mute" else tone])
        self.port_dot.itemconfig(self._dot, fill=self.widgets.c[tone])

    def release_port(self):
        port = self.port_var.get()
        if not port:
            self.log("Erst einen seriellen Port wählen.", "warn")
            return
        pid, name = ports.find_port_owner(port)
        if pid is None:
            self.log(f"{port} ist nicht blockiert.", "ok")
            return
        if not messagebox.askyesno(
                "Port freigeben",
                f"Prozess '{name}' (PID {pid}) hält {port} belegt.\n\n"
                "Prozess beenden?", icon="warning"):
            return
        ok, message = ports.release_port(port)
        self.log(message, "ok" if ok else "err")

    def browse_project(self):
        path = filedialog.askdirectory(title="Projektordner wählen")
        if path:
            self.project_var.set(path)
            self.scan_folder()

    def scan_folder(self, log_result=True):
        folder = self.project_var.get().strip()
        if not folder:
            return
        if not os.path.isdir(folder):
            self.log(f"Kein Ordner: {folder}", "warn")
            return

        self.mode_var.set("project")
        self._update_mode()
        self.plans = scan_project(folder)
        labels = [plan.label for plan in self.plans]
        self.plan_combo["values"] = labels

        if not self.plans:
            self.plan_var.set("")
            self.plan_info_var.set("")
            self.log(f"Keine flashbaren .bin-Dateien in {folder}.", "warn")
            self.set_status("Nichts gefunden")
            return

        self.plan_var.set(labels[0])
        self._remember_project(folder)
        if log_result:
            self.log(f"Scan: {len(self.plans)} Kandidat(en) in {folder}")
            for plan in self.plans[:6]:
                self.log(f"  {plan.label}")
        self._show_plan()
        self.set_status(f"Vorschlag: {self.plans[0].label}")

    def _selected_plan(self):
        return next((p for p in self.plans if p.label == self.plan_var.get()), None)

    def _show_plan(self):
        plan = self._selected_plan()
        if not plan:
            self.plan_info_var.set("")
            return
        base = self.project_var.get().strip() or None
        built = time.strftime("%d.%m.%Y %H:%M", time.localtime(plan.mtime))
        info = f"Stand: {built}   Chip: {plan.chip}\n{plan.describe(base)}"
        if plan.note:
            info += f"\n{plan.note}"
        self.plan_info_var.set(info)

    def _remember_project(self, folder):
        folder = os.path.abspath(folder)
        if folder in self.recent_projects:
            self.recent_projects.remove(folder)
        self.recent_projects.insert(0, folder)
        del self.recent_projects[8:]
        self.project_combo["values"] = self.recent_projects

    def browse_firmware(self):
        path = filedialog.askopenfilename(
            title="Firmware .bin wählen",
            filetypes=[("Firmware-Binaries", "*.bin"), ("Alle Dateien", "*.*")])
        if not path:
            return
        self.firmware_var.set(path)
        name = os.path.basename(path).lower()
        self.addr_var.set("0x0" if ("merged" in name or "factory" in name)
                          else "0x10000")

    def _base_args(self):
        return ["--chip", "auto", "--port", self.port_var.get(),
                "--baud", self.baud_var.get()]

    def _before_arg(self):
        """Ohne Auto-Reset darf esptool nicht selbst resetten — der Boot-Modus
        wurde dort von Hand über IO0/GND hergestellt."""
        return ["--before", "no_reset" if self.no_autoreset_var.get()
                else "default_reset"]

    def _after_arg(self, after):
        return ["--after", "no_reset" if self.no_autoreset_var.get() else after]

    def _confirm_manual_boot(self, action):
        if not self.no_autoreset_var.get():
            return True
        return messagebox.askokcancel(
            "Boot-Modus nötig",
            "Dieses Board hat keinen Auto-Reset.\n\n"
            f"Vor dem {action}:\n"
            "  1. IO0 mit GND brücken\n"
            "  2. Reset auslösen (EN kurz auf GND oder Strom trennen)\n"
            "  3. Brücke währenddessen gesteckt lassen\n\n"
            f"Nach dem {action}: Brücke entfernen und Reset.\n\n"
            "Board ist jetzt im Boot-Modus?", icon="warning")

    def _flash_parts(self):
        """-> [(offset, pfad)] für den aktuellen Modus, oder None."""
        if self.mode_var.get() == "project":
            plan = self._selected_plan()
            if not plan:
                self.log("Erst einen Projektordner scannen und Kandidat wählen.",
                         "warn")
                return None
            if plan.missing:
                self.log("Dateien fehlen: " + ", ".join(
                    os.path.basename(m) for m in plan.missing), "warn")
                return None
            return plan.parts

        firmware = self.firmware_var.get().strip()
        if not firmware or not os.path.isfile(firmware):
            self.log("Erst eine gültige .bin-Datei wählen.", "warn")
            return None
        return [(self.addr_var.get().strip() or "0x10000", firmware)]

    def _ready(self):
        """Vorbedingungen jeder esptool-Aktion."""
        if esptool_runner.esptool is None or serial is None:
            self.log("esptool/pyserial nicht installiert.", "warn")
            return False
        if self.busy:
            self.log("Beschäftigt — laufende Operation abwarten.", "warn")
            return False
        if not self.port_var.get():
            self.log("Erst einen seriellen Port wählen.", "warn")
            return False
        if self._monitor_running():
            self.log("Monitor wird pausiert — esptool braucht den Port exklusiv.")
            self.stop_monitor()
        return True

    def flash_firmware(self):
        if not self._ready():
            return
        parts = self._flash_parts()
        if not parts:
            return
        if not self._confirm_manual_boot("Upload"):
            return
        args = self._base_args() + self._before_arg() + self._after_arg("hard_reset")
        args += ["write_flash", "-z"]
        for offset, path in parts:
            args += [offset, path]
        names = ", ".join(os.path.basename(p) for _o, p in parts)
        hint = ("IO0-Brücke entfernen und Reset — dann startet die Firmware."
                if self.no_autoreset_var.get() else "")
        self._start_esptool(args, f"Flashe {names}", done_hint=hint)

    def erase_flash(self):
        if not self._ready():
            return
        if not messagebox.askyesno(
                "Flash löschen",
                f"Den gesamten Flash auf {self.port_var.get()} löschen?\n\n"
                "Danach muss die Firmware neu geschrieben werden.", icon="warning"):
            return
        if not self._confirm_manual_boot("Löschen"):
            return
        args = (self._base_args() + self._before_arg()
                + ["--after", "no_reset", "erase_flash"])
        self._start_esptool(args, "Lösche Flash")

    def check_device(self):
        if not self._ready():
            return
        if not self._confirm_manual_boot("Verbindungstest"):
            return
        args = (self._base_args() + self._before_arg()
                + ["--after", "no_reset", "flash_id"])
        self._start_esptool(args, "Gerät prüfen")

    def export_merged(self):
        """Den gewählten Kandidaten zu einer factory.bin ab 0x0 zusammenfügen."""
        if self.busy:
            self.log("Beschäftigt — laufende Operation abwarten.", "warn")
            return
        if self.mode_var.get() != "project":
            self.log("Export geht nur im Projektordner-Modus.", "warn")
            return
        plan = self._selected_plan()
        if not plan:
            self.log("Erst einen Kandidaten wählen.", "warn")
            return

        project = os.path.basename(self.project_var.get().rstrip(os.sep)) or "firmware"
        target = filedialog.asksaveasfilename(
            title="Zusammengeführte .bin speichern",
            initialfile=f"{project}_factory.bin", defaultextension=".bin",
            filetypes=[("Firmware-Binary", "*.bin")])
        if not target:
            return

        if len(plan.parts) == 1 and plan.parts[0][0] in ("0x0", "0x00"):
            try:
                shutil.copyfile(plan.parts[0][1], target)
            except OSError as error:
                self.log(f"Export fehlgeschlagen: {error}", "err")
                return
            self.log(f"Bereits ein Komplettimage — kopiert nach {target}", "ok")
            self.set_status("Export abgeschlossen")
            return

        args = ["--chip", plan.chip, "merge_bin", "-o", target,
                "--flash_mode", "dio", "--flash_size", plan.flash_size]
        for offset, path in plan.parts:
            args += [offset, path]
        self._start_esptool(args, f"Exportiere {os.path.basename(target)}")

    def _start_esptool(self, args, action, done_hint=""):
        self._begin_task(action)
        self.log("$ esptool " + " ".join(args))
        threading.Thread(target=self._esptool_worker,
                         args=(args, action, done_hint), daemon=True).start()

    def _esptool_worker(self, args, action, done_hint):
        def emit(line):
            self.queue.put(("log", line))
            percent = esptool_runner.parse_percent(line)
            if percent is not None:
                self.queue.put(("progress", percent))

        code = esptool_runner.run(args, emit)
        if code == 0:
            self.queue.put(("progress", 100))
            self.queue.put(("status", f"{action} — abgeschlossen"))
            self.queue.put(("log", (f"{action} abgeschlossen.", "ok")))
            if done_hint:
                self.queue.put(("log", (done_hint, "warn")))
        else:
            self.queue.put(("status", f"{action} — fehlgeschlagen (Code {code})"))
            self.queue.put(("log", (f"esptool-Fehler (Code {code}).", "err")))
            self.queue.put(("log", (self._failure_hint(), "warn")))
        self.queue.put(("done", None))

    def _failure_hint(self):
        if self.no_autoreset_var.get():
            return ("Ohne Auto-Reset: IO0 auf GND gebrückt und danach Reset "
                    "ausgelöst? Verkabelung TX/RX? Sonst Boot-Check laufen lassen.")
        return ("Anderes Kabel oder Port, niedrigere Baudrate, oder BOOT-Taste "
                "beim 'Connecting…' gedrückt halten.")

    def reset_board(self):
        if serial is None or self.busy:
            self.log("Reset gerade nicht möglich.", "warn")
            return
        port = self.port_var.get()
        if not port:
            self.log("Erst einen seriellen Port wählen.", "warn")
            return

        monitoring = self._monitor_running()
        if monitoring:
            self.stop_monitor()
        try:
            with serial.Serial(port, 115200, timeout=1) as connection:
                # EN (RTS) pulsen, GPIO0 (DTR) high lassen -> normaler Boot
                connection.setDTR(False)
                connection.setRTS(True)
                time.sleep(0.1)
                connection.setRTS(False)
                time.sleep(0.05)
            self.log(f"Reset-Puls auf {port} gesendet.", "ok")
            self.set_status("ESP32 zurückgesetzt")
        except (OSError, serial.SerialException) as error:
            self.log(f"Reset fehlgeschlagen: {error}", "err")
            self.set_status("Fehler: Reset")
        if monitoring:
            self.after(300, self.start_monitor)

    def boot_check(self):
        """Passiv mithören und den Bootzustand einordnen: kommt nichts an,
        bootet das Board normal, oder ist der Download-Modus aktiv?"""
        if serial is None:
            self.log("pyserial nicht installiert.", "warn")
            return
        if self.busy:
            self.log("Beschäftigt — laufende Operation abwarten.", "warn")
            return
        port = self.port_var.get()
        if not port:
            self.log("Erst einen seriellen Port wählen.", "warn")
            return
        if self._monitor_running():
            self.stop_monitor()

        self._begin_task("Boot-Check")
        self.log(f"Boot-Check — {BOOT_CHECK_SECONDS}s mithören auf {port}", "cmd")
        self.log("Jetzt am Board Reset auslösen.", "warn")
        self.log("Für den Boot-Modus-Test: IO0 auf GND brücken, dann Reset.", "warn")
        threading.Thread(target=self._boot_check_worker, args=(port,),
                         daemon=True).start()

    def _boot_check_worker(self, port):
        received = ""
        try:
            with serial.Serial(port, 115200, timeout=0.3) as connection:
                connection.dtr = False       # rein passiv mithören
                connection.rts = False
                connection.reset_input_buffer()
                deadline = time.time() + BOOT_CHECK_SECONDS
                while time.time() < deadline:
                    chunk = connection.read(256)
                    if not chunk:
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    received += text
                    for line in text.splitlines():
                        if line.strip():
                            self.queue.put(("log", "  " + line.strip()))
                    if "waiting for download" in received:
                        break
        except (OSError, serial.SerialException) as error:
            self.queue.put(("log", (f"Boot-Check-Fehler: {error}", "err")))
            self.queue.put(("log", "  Port belegt? 'Port freigeben' benutzen."))
            self.queue.put(("status", "Boot-Check fehlgeschlagen"))
            self.queue.put(("done", None))
            return

        for message, tone, status in self._boot_check_verdict(received):
            self.queue.put(("log", (message, tone)))
            if status:
                self.queue.put(("status", status))
        self.queue.put(("done", None))

    @staticmethod
    def _boot_check_verdict(received):
        """-> [(meldung, stufe, status)] passend zum Mitgehörten."""
        if "waiting for download" in received or "DOWNLOAD_BOOT" in received:
            return [
                ("Download-Modus aktiv — der Boot-Teil funktioniert.", "ok", None),
                ("Scheitert der Upload dennoch, ist Adapter-TX zu Board-RX0 "
                 "vertauscht oder defekt.", "dim", "Download-Modus aktiv"),
            ]
        if any(marker in received for marker in ("rst:", "boot:", "ets ")):
            return [
                ("Board bootet, TX-Leitung in Ordnung — aber normaler Boot, "
                 "kein Download-Modus.", "ok", None),
                ("Die IO0-Brücke lag beim Reset nicht an. Brücke prüfen und "
                 "Reset wiederholen, während sie steckt.", "warn",
                 "Boot-Check: normaler Boot"),
            ]
        if received.strip():
            return [("Daten empfangen, aber kein Boot-Banner erkennbar. "
                     "Baudrate und Kabel prüfen.", "warn", "Boot-Check: unklar")]
        return [("Nichts empfangen. Stromversorgung (3V3 vom Adapter reicht oft "
                 "nicht, 5V nutzen, GND gemeinsam), Reset ausgelöst, oder "
                 "Board-TX0 zu Adapter-RX falsch verdrahtet.", "err",
                 "Boot-Check: keine Daten")]

    def _monitor_running(self):
        return bool(self.monitor_thread and self.monitor_thread.is_alive())

    def toggle_monitor(self):
        if self._monitor_running():
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if serial is None:
            self.log("pyserial nicht installiert.", "warn")
            return
        if self.busy:
            self.log("Während des Flashens kein Monitor möglich.", "warn")
            return
        if self._monitor_running():
            return
        port = self.port_var.get()
        if not port:
            self.log("Erst einen seriellen Port wählen.", "warn")
            return

        self.monitor_stop.clear()
        self.monitor_thread = threading.Thread(
            target=self._monitor_worker,
            args=(port, int(self.monitor_baud_var.get())), daemon=True)
        self.monitor_thread.start()
        self.monitor_button.config(text="Stop")
        self.show_tab("Monitor")
        self.set_status(f"Monitor: {port} @ {self.monitor_baud_var.get()}")

    def stop_monitor(self):
        self.monitor_stop.set()
        thread = self.monitor_thread
        if thread:
            thread.join(timeout=1.5)
            if thread.is_alive():
                # Referenz behalten, sonst würde ein zweiter Monitor denselben
                # Port ein zweites Mal öffnen.
                self.log("Monitor reagiert nicht — Port bleibt vorerst belegt.",
                         "warn")
                return
        self.monitor_thread = None
        self.monitor_button.config(text="Start")

    def _monitor_worker(self, port, baud):
        try:
            connection = serial.Serial(port, baud, timeout=MONITOR_READ_TIMEOUT)
        except (OSError, serial.SerialException, ValueError) as error:
            self.queue.put(("mon", f"--- Monitor-Fehler: {error} ---\n"))
            self.queue.put(("mon_stopped", None))
            return

        with self._serial_lock:
            self._serial = connection
        self.queue.put(("mon", f"--- verbunden: {port} @ {baud} ---\n"))
        try:
            while not self.monitor_stop.is_set():
                try:
                    data = connection.readline()
                except (OSError, serial.SerialException):
                    break
                if data:
                    self.queue.put(("mon", data.decode("utf-8", errors="replace")))
        finally:
            # Erst abmelden, dann schließen — sonst könnte send_serial auf
            # einen geschlossenen Port schreiben.
            with self._serial_lock:
                self._serial = None
                connection.close()
            self.queue.put(("mon", "--- Monitor gestoppt ---\n"))
            self.queue.put(("mon_stopped", None))

    def send_serial(self):
        text = self.send_var.get().strip()
        if not text:
            return
        with self._serial_lock:
            connection = self._serial
            if connection is None:
                self._append_monitor("--- nicht verbunden ---\n")
                return
            try:
                connection.write((text + "\n").encode("utf-8"))
            except (OSError, serial.SerialException) as error:
                self._append_monitor(f"--- Sendefehler: {error} ---\n")
                return
        self._append_monitor(f">>> {text}\n")
        self.send_var.set("")

    def clear_monitor(self):
        self.monitor_text.config(state="normal")
        self.monitor_text.delete("1.0", "end")
        self.monitor_text.config(state="disabled")

    def _append_monitor(self, text):
        self.monitor_text.config(state="normal")
        self.monitor_text.insert("end", text)
        if self.autoscroll_var.get():
            self.monitor_text.see("end")
        self.monitor_text.config(state="disabled")

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    # Worker schicken Text oder (Text, Stufe)
                    if isinstance(payload, tuple):
                        self.log(*payload)
                    else:
                        self.log(payload)
                elif kind == "mon":
                    self._append_monitor(payload)
                elif kind == "mon_stopped":
                    self.monitor_thread = None
                    self.monitor_button.config(text="Start")
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "status":
                    self.set_status(payload)
                elif kind == "done":
                    self._end_task()
        except queue.Empty:
            pass
        self.after(60, self._drain_queue)

    def _begin_task(self, action):
        self.busy = True
        self._set_actions_enabled(False)
        self.progress["value"] = 0
        self.set_status(f"{action}…")

    def _end_task(self):
        self.busy = False
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled):
        for button in (self.flash_button, self.erase_button, self.reset_button,
                       self.check_button, self.boot_check_button,
                       self.export_button, self.release_button):
            self.widgets.set_enabled(button, enabled)

    @staticmethod
    def _classify(text):
        """Nur für die englische esptool-Ausgabe; eigene Meldungen bringen ihre
        Stufe selbst mit."""
        stripped = text.lstrip()
        if stripped.startswith("$"):
            return "cmd"
        lowered = stripped.lower()
        if any(word in lowered for word in ("error", "fatal", "failed")):
            return "err"
        if "hash of data verified" in lowered or lowered.startswith("leaving"):
            return "ok"
        if stripped.startswith(("Writing at", "Reading at", "Compressed",
                                "Wrote", "Connecting", "  ")):
            return "dim"
        return ""

    def log(self, text, level=None):
        tag = level or self._classify(text)
        # Fortschrittszeilen ersetzen, sonst flutet write_flash das Log.
        is_progress = text.lstrip().startswith(("Writing at", "Reading at"))
        replace = is_progress and self._last_line_was_progress and self.log_entries
        if replace:
            self.log_entries[-1] = (text, tag)
        else:
            self.log_entries.append((text, tag))
        del self.log_entries[:-MAX_LOG_LINES]
        self._last_line_was_progress = is_progress

        self.log_text.config(state="normal")
        if replace:
            self.log_text.delete("end-2l", "end-1l")
        self.log_text.insert("end", text + "\n", tag)
        # Auch das Widget kürzen, sonst wächst es über die Sitzung endlos.
        excess = int(self.log_text.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.log_text.delete("1.0", f"{excess + 1}.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _render_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        for text, tag in self.log_entries:
            self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def set_status(self, text):
        self.status_var.set(text)

    def _on_close(self):
        self.monitor_stop.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.5)
        settings.save(self._collect_settings())
        self.destroy()
