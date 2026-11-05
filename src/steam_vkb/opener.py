"""Summon (and, optionally, dismiss) the Steam Game Mode on-screen keyboard.

The summon uses the Steam client URL handler ``steam://open/keyboard``.  This
is the same mechanism SDL applications use for the in-game keyboard and the
one SteamOS desktop mode's own Steam Keyboard window uses.  Steam types into
the focused application through its virtual input device, so no text-input
plumbing is needed from the compositor side.
"""

from __future__ import annotations

import shutil
import subprocess

from .config import sanitize_env

STEAM_OPEN_URL = "steam://open/keyboard"


def _default_open_cmd() -> list[str] | None:
    """Auto-detect how to invoke the Steam URL handler on this system."""
    if shutil.which("steam"):
        return ["steam", STEAM_OPEN_URL]
    if shutil.which("xdg-open"):
        return ["xdg-open", STEAM_OPEN_URL]
    return None


def summon(cfg_open_cmd: list[str] | None, env: dict[str, str] | None = None) -> bool:
    """Summon the Steam keyboard overlay. Returns True if a process started."""
    cmd = cfg_open_cmd if cfg_open_cmd else _default_open_cmd()
    if not cmd:
        return False
    try:
        subprocess.Popen(  # noqa: S603 - arguments fixed
            cmd,
            env=sanitize_env(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True
