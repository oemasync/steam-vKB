"""steam-vKB top bar: ESC, CTRL, ALT, F1-F9 companion toolbar.

A small always-on-top strip that appears alongside the Steam Game Mode
on-screen keyboard and injects the extra keys Steam's keyboard does not
expose (ESC, CTRL, ALT, F1..F9) into the focused application via xdotool.

Runs as a standalone process launched by the bridge on summon and torn down
on dismiss.  Uses the X11 (Xwayland) backend so the window can be positioned
and kept above by the client.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

os.environ.setdefault("GDK_BACKEND", "x11")

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

KEYS = ["ESC", "CTRL", "ALT", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"]

XKEY = {
    "ESC": "Escape",
    "CTRL": "Control_L",
    "ALT": "Alt_L",
}


def send_key(name: str) -> None:
    xname = XKEY.get(name.upper(), name)
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return
    try:
        subprocess.Popen(
            [xdotool, "key", xname],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


class TopBar(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="steam-vKB top bar")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(4)
        box.set_margin_end(4)
        for key in KEYS:
            btn = Gtk.Button(label=key)
            btn.connect("clicked", lambda _b, k=key: send_key(k))
            box.pack_start(btn, False, False, 0)
        self.add(box)
        self.show_all()

        # Periodically keep ourselves positioned above the Steam keyboard.
        GLib.timeout_add(500, self._reposition)

    def _reposition(self) -> bool:
        xdotool = shutil.which("xdotool")
        wmctrl = shutil.which("wmctrl")
        if not (xdotool and wmctrl):
            return True
        try:
            out = subprocess.check_output(
                [wmctrl, "-l"], text=True, stderr=subprocess.DEVNULL
            )
        except (OSError, subprocess.CalledProcessError):
            return True
        kb_wid = None
        for line in out.splitlines():
            if "On-screen Keyboard" in line:
                kb_wid = line.split()[0]
                break
        if not kb_wid:
            return True
        # get geometry
        try:
            info = subprocess.check_output(
                [xdotool, "getwindowgeometry", "--shell", kb_wid],
                text=True, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return True
        geom = {}
        for line in info.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                geom[k] = v
        x = int(geom.get("X", "0"))
        y = int(geom.get("Y", "0"))
        w = int(geom.get("WIDTH", "0"))
        # place bar just above the keyboard, same x, width clamped
        bar_w = self.get_allocated_width() or 400
        bar_x = x + max(0, (w - bar_w) // 2)
        bar_y = max(0, y - 40)
        wid = self.get_window().get_xid() if self.get_window() else None
        if wid:
            subprocess.Popen(
                [xdotool, "windowmove", str(wid), str(bar_x), str(bar_y)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                [xdotool, "windowraise", str(wid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True


def main() -> int:
    TopBar()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
