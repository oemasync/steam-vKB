"""Self-contained Plasma virtual keyboard for the Steam Game Mode keyboard.

KWin publishes a ``zwp_input_method_v1`` global on the private socket it hands
us via ``WAYLAND_SOCKET``.  On ``activate`` we receive a context and show our
own on-screen keyboard window; keystrokes are injected back through that context
(``commit_string`` / ``keysym``), so no Steam process and no login are needed.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import traceback

# Force XWayland so the keyboard is an X11 window: KWin's kwinrulesrc (keep-above,
# skip-taskbar) keys on the X11 WM_CLASS and applies to XWayland windows, matching
# the original Bazzite Steam keyboard. The Wayland input-method connection is
# handled separately via pywayland and is unaffected by this.
os.environ.setdefault("GDK_BACKEND", "x11")

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib
    HAS_GTK = True
except Exception:  # noqa: BLE001
    HAS_GTK = False
    Gtk = Gdk = GLib = None  # type: ignore[assignment]

from pywayland.client import Display
from pywayland.protocol import input_method_unstable_v1 as im_v1

from . import PROTOCOL_GLOBAL
from .config import Config

# XKB keysyms for the special keys.
KEYSYM = {
    "ESC": 0xFF1B,
    "ENTER": 0xFF0D,
    "BACKSPACE": 0xFF08,
    "TAB": 0xFF09,
    "DELETE": 0xFFFF,
    "LEFT": 0xFF51,
    "RIGHT": 0xFF53,
    "UP": 0xFF52,
    "DOWN": 0xFF54,
    "HOME": 0xFF50,
    "END": 0xFF57,
    "CTRL": 0xFFE3,   # Control_L
    "ALT": 0xFFE9,    # Alt_L
}
for i in range(1, 10):
    KEYSYM[f"F{i}"] = 0xFFBD + (i - 1)  # F1 = 0xFFBE

# Keyboard layout: rows of keys.  Each key is (label, value) where value is
# either a single character to commit, or a special token like "BACKSPACE".
LAYOUT = [
    ["ESC", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"],
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "BACKSPACE"],
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l", "ENTER"],
    ["z", "x", "c", "v", "b", "n", "m", ",", ".", "/"],
    ["CTRL", "ALT", "SPACE", "LEFT", "RIGHT", "UP", "DOWN"],
]


class _SummonState:
    """Tracks open/close transitions across context churn (one context per activation)."""

    def __init__(self) -> None:
        self.open = False
        self.last_summon = 0.0

    def open_now(self, now: float) -> bool:
        """Transition closed -> open, debounced."""
        if self.open or (now - self.last_summon) < 0.150:
            return False
        self.open = True
        self.last_summon = now
        return True

    def close(self) -> None:
        self.open = False


if HAS_GTK:
    class KeyboardWindow(Gtk.Window):
        def __init__(self, on_key):
            super().__init__(title="Steam Input On-screen Keyboard")
            self._on_key = on_key
            try:
                self.set_wmclass("steamwebhelper", "steam")
            except Exception:  # noqa: BLE001
                pass
            self.set_decorated(False)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_keep_above(True)
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            self.set_resizable(False)

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            outer.set_margin_top(6)
            outer.set_margin_bottom(6)
            outer.set_margin_start(6)
            outer.set_margin_end(6)

            for row in LAYOUT:
                hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                for key in row:
                    label = "SPACE" if key == "SPACE" else key
                    btn = Gtk.Button(label=label)
                    btn.set_size_request(46 if len(label) <= 3 else 72, 40)
                    btn.connect("clicked", lambda _b, k=key: self._on_key(k))
                    hbox.pack_start(btn, False, False, 0)
                outer.pack_start(hbox, False, False, 0)

            self.add(outer)
            self.show_all()
            self.hide()


else:
    class KeyboardWindow:
        def __init__(self, on_key):
            self._on_key = on_key
        def show_all(self): pass
        def present(self): pass
        def hide(self): pass
class SteamVkbBridge:
    def __init__(self, config: Config, display_factory=None, summoner=None):
        self._config = config
        self._display_factory = display_factory
        self._summoner = summoner
        self._display = None
        self._context = None
        self._serial = 1
        self._window = None
        self._on_key_cb = None
        self._bound = False
        self._state = _SummonState()

    def _log(self, msg: str) -> None:
        try:
            os.write(2, f"steam-vkb: {msg}\n".encode())
        except OSError:
            pass

    def _on_key(self, key: str) -> None:
        ctx = self._context
        if ctx is None:
            self._log(f"key {key!r} ignored: no active context")
            return
        serial = self._serial
        self._serial += 1
        try:
            if key == "SPACE":
                ctx.commit_string(serial, " ")
            elif len(key) == 1 and key.isprintable() and key not in KEYSYM:
                ctx.commit_string(serial, key)
            elif key in KEYSYM:
                sym = KEYSYM[key]
                now = int(time.monotonic() * 1000) & 0xFFFFFFFF
                ctx.keysym(serial, now, sym, 1, 0)  # pressed
                s2 = self._serial
                self._serial += 1
                ctx.keysym(s2, now, sym, 0, 0)  # released
            else:
                self._log(f"unknown key {key!r}")
                return
            self._log(f"injected {key!r}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"inject failed for {key!r}: {exc!r}")

    def on_activate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        self._log("activate")
        self._context = context
        try:
            context.dispatcher["commit_state"] = self._on_commit_state
        except Exception:  # noqa: BLE001
            pass
        now = time.monotonic()
        if self._state.open_now(now):
            if self._summoner is not None:
                try:
                    self._summoner(self._config.open_cmd if self._config.open_cmd else None)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"summoner raised: {exc!r}")
            if self._window is not None:
                try:
                    self._window.show_all()
                    self._window.present()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"show failed: {exc!r}")
        else:
            self._log("activate ignored (debounce or already open)")

    def _on_commit_state(self, proxy, serial) -> None:  # noqa: ANN001
        try:
            self._serial = int(serial) + 1
        except (TypeError, ValueError):
            pass

    def on_deactivate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        self._log("deactivate")
        self._context = None
        if self._state.open:
            self._state.close()
        if self._window is not None:
            try:
                self._window.hide()
            except Exception:  # noqa: BLE001
                pass

    def bind_global(self, registry, name: int, iface: str, version: int):
        if iface != PROTOCOL_GLOBAL:
            return None
        self._log(f"binding {iface} v{version} (name={name})")
        keyboard = registry.bind(name, im_v1.ZwpInputMethodV1, min(version, 1))
        keyboard.dispatcher["activate"] = self.on_activate
        keyboard.dispatcher["deactivate"] = self.on_deactivate
        self._bound = True
        self._log(f"{iface} bound")
        return keyboard

    def run(self) -> int:
        socket_raw = os.environ.get("WAYLAND_SOCKET")
        self._log(f"starting (pid={os.getpid()}, WAYLAND_SOCKET={socket_raw!r})")
        if self._display_factory is not None:
            display = self._display_factory()
        elif socket_raw and socket_raw.lstrip("-").isdigit():
            display = Display(int(socket_raw))
        else:
            display = Display(None)
        self._display = display

        try:
            display.connect()
            self._log("wayland connection established")
        except Exception as exc:  # noqa: BLE001
            self._log(f"FATAL: cannot connect: {exc!r}")
            return 0

        registry = display.get_registry()
        registry.dispatcher["global"] = self.bind_global

        deadline = time.monotonic() + 5.0
        try:
            while not getattr(self, "_bound", False) and time.monotonic() < deadline:
                if display.dispatch(block=True) <= 0:
                    self._log("connection closed while waiting for IM global")
                    break
            if getattr(self, "_bound", False):
                self._log("IM global bound")
            else:
                self._log("WARNING: IM global not bound within timeout")
        except Exception as exc:  # noqa: BLE001
            self._log(f"FATAL: dispatch failed during bind wait: {exc!r}\n{traceback.format_exc()}")
            try:
                display.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return 0

        self._bound = getattr(self, "_bound", False)

        # Build the keyboard window (may fail headless / without a display).
        gui = HAS_GTK
        if gui:
            try:
                self._window = KeyboardWindow(self._on_key)
                self._log("keyboard window created")
            except Exception as exc:  # noqa: BLE001
                self._log(f"no GUI available ({exc!r}); running headless")
                self._window = None
                gui = False
        else:
            self._window = None
            self._log("headless mode (no GTK)")


        if gui:
            def tick():
                try:
                    rc = display.dispatch(block=False)
                except Exception as exc2:  # noqa: BLE001
                    self._log(f"dispatch raised: {exc2!r}")
                    Gtk.main_quit()
                    return False
                if rc is not None and rc <= 0:
                    self._log("input-method connection closed; exiting")
                    Gtk.main_quit()
                    return False
                try:
                    display.flush()
                except Exception:  # noqa: BLE001
                    pass
                return True

            GLib.timeout_add(16, tick)
            self._log("entering GTK main loop")
            Gtk.main()
        else:
            # Headless fallback (tests / no display): blocking dispatch loop.
            try:
                while True:
                    try:
                        rc = display.dispatch(block=True)
                    except Exception as exc2:  # noqa: BLE001
                        self._log(f"dispatch raised: {exc2!r}")
                        break
                    if rc <= 0:
                        self._log("input-method connection closed; exiting")
                        break
            except KeyboardInterrupt:
                pass

        try:
            display.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return 0

    def main(self) -> int:
        return self.run()


import faulthandler
faulthandler.enable()

def main(argv=None) -> int:
    del argv
    config = Config.from_env()
    bridge = SteamVkbBridge(config)
    bridge._log(f"main() entered, python={sys.version.split()[0]}, debug={config.debug}")

    def _on_signal(signum, frame):  # noqa: ANN001
        bridge._log(f"received signal {signum}; exiting")
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            pass
    rc = bridge.run()
    bridge._log(f"main() returning {rc}")
    return rc
