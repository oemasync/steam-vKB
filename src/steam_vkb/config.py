"""Runtime configuration and environment plumbing.

KWin launches the selected virtual keyboard with a dedicated wayland socket in
the ``WAYLAND_SOCKET`` environment variable plus a few variables of its own
(``QT_QPA_PLATFORM=wayland``, ``MALIIT_ENABLE_ANIMATIONS=0``).  Those must NOT
leak into any child we spawn (they would try to use KWin's private input-method
socket), so they are stripped before summoning Steam.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field

# Variables KWin exports to the input-method process that must not leak to Steam.
KWIN_IM_ENV_KEYS = (
    "WAYLAND_SOCKET",
    "QT_QPA_PLATFORM",
    "MALIIT_ENABLE_ANIMATIONS",
    "KWIN_IM_WAYLAND_DEBUG",
    "WAYLAND_DEBUG",
)

TRUE_VALUES = ("1", "true", "yes", "on")


def sanitize_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict with KWin's input-method-only variables removed."""
    clean = dict(os.environ if env is None else env)
    for key in KWIN_IM_ENV_KEYS:
        clean.pop(key, None)
    return clean


@dataclass
class Config:
    open_cmd: list[str] | None = None  # None = auto-detect in opener.py
    close_cmd: list[str] | None = None
    close_on_deactivate: bool = False
    debug: bool = False

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        cfg = Config()
        if env.get("STEAM_VKB_OPEN", "").strip():
            cfg.open_cmd = shlex.split(env["STEAM_VKB_OPEN"])
        if env.get("STEAM_VKB_CLOSE", "").strip():
            cfg.close_cmd = shlex.split(env["STEAM_VKB_CLOSE"])
        cfg.close_on_deactivate = env.get(
            "STEAM_VKB_CLOSE_ON_DEACTIVATE", ""
        ).strip().lower() in TRUE_VALUES
        cfg.debug = env.get("STEAM_VKB_DEBUG", "").strip().lower() in TRUE_VALUES
        return cfg
