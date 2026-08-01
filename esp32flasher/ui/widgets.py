"""Themefähige Bausteine für die Oberfläche.

Buttons sind tk.Label statt tk.Button: unter macOS ignoriert der native
Aqua-Button die Hintergrundfarbe, ein Label rendert sie zuverlässig.
"""

import tkinter as tk
from tkinter import ttk

from ..theme import MONO, SANS


class Widgets:
    def __init__(self, palette):
        self.c = palette

    def card(self, parent, title):
        """Panel mit Kapitälchen-Kopfzeile. -> (rahmen, inhalt)"""
        color = self.c
        outer = tk.Frame(parent, bg=color["surface"],
                         highlightbackground=color["border"],
                         highlightcolor=color["border"], highlightthickness=1)
        tk.Label(outer, text=" ".join(title.upper()), bg=color["surface"],
                 fg=color["mute"], font=(SANS, 9), anchor="w").pack(
            fill="x", padx=18, pady=(13, 9))
        body = tk.Frame(outer, bg=color["surface"])
        body.pack(fill="both", expand=True, padx=18, pady=(0, 15))
        return outer, body

    def separator(self, parent):
        return tk.Frame(parent, bg=self.c["border"], height=1)

    def button(self, parent, text, command, kind="secondary", small=False):
        color = self.c
        styles = {
            "primary":   (color["accent"], color["on_accent"], color["accent_hi"]),
            "danger":    (color["surface2"], color["danger"], color["hover"]),
            "secondary": (color["surface2"], color["text"], color["hover"]),
        }
        background, foreground, hover = styles[kind]
        button = tk.Label(parent, text=text, bg=background, fg=foreground,
                          cursor="hand2", disabledforeground=color["on_disabled"],
                          padx=14 if small else 18, pady=7 if small else 11,
                          font=(SANS, 11, "normal" if small else "bold"))
        button.enabled_bg = background
        button.disabled_bg = color["disabled"]
        self._bind_action(button, command, lambda: button.config(bg=hover),
                          lambda: button.config(bg=button.enabled_bg))
        return button

    def link(self, parent, text, command):
        """Textaktion ohne Buttonfläche."""
        color = self.c
        label = tk.Label(parent, text=text, bg=color["surface"], fg=color["dim"],
                         cursor="hand2", font=(SANS, 10),
                         disabledforeground=color["on_disabled"])
        label.enabled_bg = color["surface"]
        label.disabled_bg = color["surface"]
        self._bind_action(label, command,
                          lambda: label.config(fg=color["text"]),
                          lambda: label.config(fg=color["dim"]))
        return label

    @staticmethod
    def _bind_action(widget, command, on_enter, on_leave):
        def active(_event=None):
            return str(widget["state"]) != "disabled"

        widget.bind("<Button-1>", lambda _e: active() and command())
        widget.bind("<Enter>", lambda _e: active() and on_enter())
        widget.bind("<Leave>", lambda _e: active() and on_leave())

    @staticmethod
    def set_enabled(widget, enabled):
        widget.config(state="normal" if enabled else "disabled",
                      bg=widget.enabled_bg if enabled else widget.disabled_bg)

    def radio(self, parent, text, variable, value, command):
        color = self.c
        return tk.Radiobutton(parent, text=text, variable=variable, value=value,
                              command=command, bg=color["surface"],
                              fg=color["text"], selectcolor=color["surface2"],
                              activebackground=color["surface"],
                              activeforeground=color["text"],
                              highlightthickness=0, font=(SANS, 11),
                              cursor="hand2", anchor="w")

    def check(self, parent, text, variable):
        color = self.c
        return tk.Checkbutton(parent, text=text, variable=variable,
                              bg=color["surface"], fg=color["dim"],
                              selectcolor=color["surface2"],
                              activebackground=color["surface"],
                              activeforeground=color["text"],
                              highlightthickness=0, font=(SANS, 10),
                              cursor="hand2", anchor="w")

    def entry(self, parent, variable):
        color = self.c
        return tk.Entry(parent, textvariable=variable, bg=color["surface2"],
                        fg=color["text"], insertbackground=color["text"],
                        relief="flat", highlightthickness=1,
                        highlightbackground=color["border"],
                        highlightcolor=color["accent"],
                        disabledbackground=color["surface"],
                        disabledforeground=color["on_disabled"], font=(SANS, 11))

    def label(self, parent, text, tone="text", size=11):
        return tk.Label(parent, text=text, bg=self.c["surface"], fg=self.c[tone],
                        font=(SANS, size))

    def console(self, parent, height):
        """Monospace-Textfläche für Log und Monitor."""
        color = self.c
        return tk.Text(parent, height=height, bg=color["log_bg"],
                       fg=color["log_fg"], insertbackground=color["text"],
                       wrap="word", relief="flat", highlightthickness=0,
                       font=(MONO, 10), padx=10, pady=8, spacing1=1)

    def segmented(self, parent, options, active, on_select):
        """Umschalter wie Auto | Hell | Dunkel."""
        color = self.c
        box = tk.Frame(parent, bg=color["border"], highlightthickness=0)
        for value, text in options:
            selected = value == active
            item = tk.Label(box, text=text, cursor="hand2",
                            bg=color["surface"] if selected else color["bg"],
                            fg=color["text"] if selected else color["mute"],
                            font=(SANS, 10), padx=12, pady=4)
            item.bind("<Button-1>", lambda _e, v=value: on_select(v))
            item.pack(side="left", padx=(0, 1))
        return box

    def apply_ttk_style(self, root):
        """Comboboxen, Fortschrittsbalken und Scrollbalken einfärben."""
        color = self.c
        root.configure(bg=color["bg"])
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=color["surface2"],
                        background=color["surface2"], foreground=color["text"],
                        arrowcolor=color["dim"], bordercolor=color["border"],
                        lightcolor=color["surface2"], darkcolor=color["surface2"],
                        insertcolor=color["text"], padding=5, relief="flat")
        style.map("TCombobox",
                  fieldbackground=[("readonly", color["surface2"]),
                                   ("disabled", color["surface"])],
                  foreground=[("disabled", color["on_disabled"])],
                  arrowcolor=[("disabled", color["on_disabled"])])
        style.configure("Flash.Horizontal.TProgressbar",
                        troughcolor=color["surface2"], background=color["accent"],
                        bordercolor=color["bg"], lightcolor=color["accent"],
                        darkcolor=color["accent"], thickness=4)
        style.configure("Vertical.TScrollbar", background=color["surface2"],
                        troughcolor=color["log_bg"], bordercolor=color["log_bg"],
                        arrowcolor=color["mute"], lightcolor=color["surface2"],
                        darkcolor=color["surface2"], relief="flat")
        style.map("Vertical.TScrollbar",
                  background=[("active", color["hover"]),
                              ("pressed", color["hover"])])
        for option, value in (("background", color["surface2"]),
                              ("foreground", color["text"]),
                              ("selectBackground", color["accent"]),
                              ("selectForeground", color["on_accent"]),
                              ("borderWidth", 0)):
            root.option_add(f"*TCombobox*Listbox.{option}", value)
