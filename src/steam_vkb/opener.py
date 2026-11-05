"""Summon (and, optionally, dismiss) the Steam Game Mode on-screen keyboard.

The summon uses the Steam client URL handler ``steam://open/keyboard``.  This
is the same mechanism SDL applications use for the in-game keyboard and the
one SteamOS desktop mode's own Steam Keyboard window uses.  Steam types into
the focused application through its virtual input device, so no text-input
plumbing is needed from the compositor side.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .config import sanitize_env


def _steam_logged_in(env=None) -> bool:
    """Best-effort check: Steam has a persisted loginusers.vdf with an account."""
    check_env = env if env is not None else os.environ
    if str(check_env.get("STEAM_VKB_SKIP_LOGIN_CHECK", "")).lower() in ("1", "true", "yes"):
        return True
    steam_root = os.path.expanduser("~/.local/share/Steam")
    loginusers = os.path.join(steam_root, "config", "loginusers.vdf")
    if not os.path.isfile(loginusers):
        return False
    try:
        with open(loginusers) as fh:
            return "AccountName" in fh.read()
    except OSError:
        return False


def _default_open_cmd() -> list[str] | None:
    """Auto-detect how to invoke the Steam URL handler on this system."""
    if shutil.which("steam"):
        return ["steam", "steam://open/keyboard"]
    if shutil.which("xdg-open"):
        return ["xdg-open", "steam://open/keyboard"]
    return None


def summon(cfg_open_cmd, env=None) -> bool:
    """Summon the Steam keyboard overlay. Returns True if a process started."""
    if not _steam_logged_in(env):
        print(
            "steam-vkb: Steam is not logged in on this account; "
            "log into Steam once (Remember me) and the keyboard will appear.",
            file=sys.stderr,
        )
        return False
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
