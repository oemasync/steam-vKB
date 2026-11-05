"""The KWin input-method client / Steam summoner.

KWin publishes a ``zwp_input_method_v1`` global for the dedicated input-method
connection it opens for the configured virtual keyboard.  On bind, KWin
immediately sends ``activate`` if a text input is already active, and sends
``activate``/``deactivate`` as text input focus moves around the session.

This bridge consumes those events and turns them into ``steam://open/keyboard``
summons, so the Steam Game Mode on-screen keyboard appears for focused text
fields.  We deliberately never take the ``grab_keyboard`` hardware-keyboard
grab and never render our own panel: Steam's keyboard is a real top-level
window kept above others by Bazzite's existing ``kwinrulesrc`` rules
(steamdeck-kde-presets, 0001-steam-virtual-keyboard.patch).

Connection lifecycle: the wayland fd KWin hands us via ``WAYLAND_SOCKET``
exists only for that one input-method connection, so a dead connection is a
terminal condition: the bridge exits cleanly (KWin already tears the process
down itself on disable; on crash-exit it restarts the desktop-file command).
"""

from __future__ import annotations

import faulthandler
import os
import signal
import sys
import time
import traceback
import subprocess
import shutil
import os as _os

from pywayland.client import Display
from pywayland.protocol import input_method_unstable_v1 as im_v1

from . import PROTOCOL_GLOBAL
from .config import Config
from .opener import summon

SUMMON_DEBOUNCE_SECONDS = 0.150


class _SummonState:
    """Tracks open/close transitions across context churn (one context per activation)."""

    def __init__(self) -> None:
        self.open = False
        self.last_summon = 0.0

    def open_now(self, now: float) -> bool:
        """Transition closed -> open, debounced."""
        if self.open or (now - self.last_summon) < SUMMON_DEBOUNCE_SECONDS:
            return False
        self.open = True
        self.last_summon = now
        return True

    def close(self) -> None:
        self.open = False


class SteamVkbBridge:
    """Owns the wayland client connection and the summon state machine."""

    def __init__(
        self,
        config: Config,
        display_factory=None,
        summoner=None,
    ) -> None:
        self._config = config
        self._display_factory = display_factory
        self._summoner = summoner if summoner is not None else summon
        self._state = _SummonState()
        self._bound = False
        self._topbar_proc = None

    # -- logging ------------------------------------------------------------
    def _log(self, msg: str) -> None:
        """Unbuffered lifecycle log to fd 2 (KWin forwards it to the journal)."""
        try:
            os.write(2, f"steam-vkb: {msg}\n".encode())
        except OSError:
            pass

    # -- event handlers -----------------------------------------------------
    def on_activate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        self._log("activate event received")
        if self._state.open_now(time.monotonic()):
            self._log("transitioning closed->open; summoning")
            try:
                ok = self._summoner(self._config.open_cmd)
            except Exception as exc:  # noqa: BLE001
                self._log(f"summon raised: {exc!r}")
                ok = False
            if not ok:
                self._log("summon command unavailable/failed")
            else:
                self._log("summon dispatched")
                self._launch_topbar()
        else:
            self._log("activate ignored (debounce or already open)")

    def on_deactivate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        if self._state.open:
            self._state.close()
            self._log("deactivate: closed")
            self._kill_topbar()
            if self._config.close_on_deactivate and self._config.close_cmd:
                self._log("trying dismiss command")
                try:
                    summon(self._config.close_cmd)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"dismiss raised: {exc!r}")

    # -- wayland plumbing ---------------------------------------------------
    def bind_global(self, registry, name: int, iface: str, version: int):
        """Registry global handler: bind zwp_input_method_v1 and wire events."""
        if iface != PROTOCOL_GLOBAL:
            return None
        self._log(f"binding {iface} v{version} (name={name})")
        keyboard = registry.bind(name, im_v1.ZwpInputMethodV1, min(version, 1))
        keyboard.dispatcher["activate"] = self.on_activate
        keyboard.dispatcher["deactivate"] = self.on_deactivate
        self._bound = True
        self._log(f"{iface} bound, activate/deactivate wired")
        return keyboard


    # -- top bar companion --------------------------------------------------
    def _topbar_script(self) -> str:
        return _os.path.join(_os.path.dirname(__file__), "topbar.py")

    def _launch_topbar(self) -> None:
        script = self._topbar_script()
        if not _os.path.isfile(script):
            self._log(f"topbar script missing: {script}")
            return
        # Prefer the system interpreter: the bridge runs inside the steam-vkb
        # venv (which has pywayland but not PyGObject/gi), while the top bar
        # needs the system python that ships PyGObject.
        py = None
        for cand in ("/usr/bin/python3", "/usr/bin/python"):
            if _os.path.isfile(cand) and _os.access(cand, _os.X_OK):
                py = cand
                break
        if py is None:
            py = shutil.which("python3") or shutil.which("python")
        if not py:
            self._log("no python for topbar")
            return
        try:
            self._topbar_proc = subprocess.Popen(  # noqa: S603
                [py, script],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={k: v for k, v in _os.environ.items()
                     if k not in ("WAYLAND_SOCKET", "QT_QPA_PLATFORM")},
            )
            self._log(f"topbar launched pid={self._topbar_proc.pid}")
        except OSError as exc:
            self._log(f"topbar launch failed: {exc!r}")

    def _kill_topbar(self) -> None:
        proc = self._topbar_proc
        self._topbar_proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._log("topbar stopped")

    def run(self) -> int:
        """Connect to KWin, bind the input method, and dispatch forever."""
        socket_raw = os.environ.get("WAYLAND_SOCKET")
        self._log(f"starting (pid={os.getpid()}, WAYLAND_SOCKET={socket_raw!r})")
        if self._display_factory is not None:
            display = self._display_factory()
        elif socket_raw and socket_raw.lstrip("-").isdigit():
            display = Display(int(socket_raw))
        else:
            # Test/dev fallback: connect the normal session wayland socket.
            display = Display(None)

        try:
            display.connect()
            self._log("wayland connection established")
        except Exception as exc:  # noqa: BLE001
            self._log(f"FATAL: cannot connect to the input-method socket: {exc!r}")
            return 0

        registry = display.get_registry()
        registry.dispatcher["global"] = self.bind_global

        # Enumerate globals and wait for the IM global to be bound.  We avoid
        # wl_display_roundtrip() here: on pywayland 0.4.19 it raises a spurious
        # "TypeError: an integer is required" from inside a cffi callback on
        # this code path, which KWin would otherwise read as a crash.
        deadline = time.monotonic() + 5.0
        try:
            while not self._bound and time.monotonic() < deadline:
                if display.dispatch(block=True) <= 0:
                    self._log("connection closed while waiting for IM global")
                    break
            if self._bound:
                self._log("IM global bound (roundtrip-equivalent complete)")
            else:
                self._log("WARNING: IM global not bound within timeout")
        except Exception as exc:  # noqa: BLE001
            self._log(f"FATAL: dispatch failed during bind wait: {exc!r}\n{traceback.format_exc()}")
            try:
                display.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return 0

        # Main loop: dispatch events; activate/deactivate arrive here.
        try:
            while True:
                try:
                    rc = display.dispatch(block=True)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"dispatch raised: {exc!r}")
                    break
                if rc <= 0:
                    self._log("input-method connection closed; exiting")
                    break
        except KeyboardInterrupt:
            return 0

        try:
            display.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return 0

    def main(self) -> int:
        return self.run()


def main(argv: list[str] | None = None) -> int:
    del argv  # No CLI flags yet; configuration is environment-driven (see README).
    faulthandler.enable()
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
