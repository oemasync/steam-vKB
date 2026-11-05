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

import os
import sys
import time

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

    # -- event handlers -----------------------------------------------------
    def on_activate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        if self._state.open_now(time.monotonic()):
            if self._config.debug:
                print("steam-vkb: text input active, summoning Steam keyboard", file=sys.stderr)
            if not self._summoner(self._config.open_cmd):
                if self._config.debug:
                    print("steam-vkb: summon command unavailable", file=sys.stderr)

    def on_deactivate(self, proxy, context) -> None:  # noqa: ANN001, ARG002
        if self._state.open:
            self._state.close()
            if self._config.debug:
                print("steam-vkb: text input deactivated", file=sys.stderr)
            if self._config.close_on_deactivate and self._config.close_cmd:
                if self._config.debug:
                    print("steam-vkb: trying dismiss command", file=sys.stderr)
                summon(self._config.close_cmd)

    # -- wayland plumbing ---------------------------------------------------
    def _log(self, msg: str, *, verbose: bool = False) -> None:
        """Lifecycle logging written straight to fd 2 (unbuffered).

        KWin forwards the child's stderr into the journal, so these appear as
        kwin_wayland lines.  Kept unbuffered on purpose: a crash must not be
        able to eat the last log line.
        """
        if verbose and not self._config.debug:
            return
        os.write(2, f"steam-vkb: {msg}\n".encode())

    def bind_global(self, registry, name: int, iface: str, version: int):
        """Registry global handler: bind zwp_input_method_v1 and wire events."""
        if iface != PROTOCOL_GLOBAL:
            return None
        self._log(f"binding {iface} v{version} (name={name})")
        keyboard = registry.bind(name, im_v1.ZwpInputMethodV1, min(version, 1))
        keyboard.dispatcher["activate"] = self.on_activate
        keyboard.dispatcher["deactivate"] = self.on_deactivate
        self._log(f"{iface} bound, activate/deactivate wired")
        return keyboard

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
        try:
            display.roundtrip()  # globals enumerated and zwp_input_method_v1 bound
            self._log("roundtrip complete (globals enumerated, IM bound if present)")
            while True:
                if display.dispatch(block=True) <= 0:
                    # 0 == KWin closed the input-method connection.
                    self._log("input-method connection closed; exiting")
                    break
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001
            self._log(f"FATAL: dispatch failed: {exc!r}")
            return 0

        try:
            display.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return 0


def main(argv: list[str] | None = None) -> int:
    del argv  # No CLI flags yet; configuration is environment-driven (see README).
    config = Config.from_env()
    bridge = SteamVkbBridge(config)
    bridge._log(f"main() entered, python={sys.version.split()[0]}, debug={config.debug}")
    rc = bridge.run()
    bridge._log(f"main() returning {rc}")
    return rc
