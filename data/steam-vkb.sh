#!/bin/sh
# steam-vkb launcher
#
# KWin runs this Exec for the "Steam Game Mode Keyboard" virtual keyboard entry.
# Entry resolution:
#   1. a venv installed by install.sh  (/opt/steam-vkb/venv)
#   2. a user-local venv               (~/.local/share/steam-vkb/venv)
#   3. system python with pywayland installed (distro / pipx setups)
prefix="/opt/steam-vkb"
user_prefix="${XDG_DATA_HOME:-$HOME/.local/share}/steam-vkb"

if [ "$STEAM_VKB_PREFIX" != "" ] && [ -x "$STEAM_VKB_PREFIX/venv/bin/python" ]; then
    prefix="$STEAM_VKB_PREFIX"
elif [ -x "$prefix/venv/bin/python" ]; then
    :
elif [ -x "$user_prefix/venv/bin/python" ]; then
    prefix="$user_prefix"
else
    prefix=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            py="$candidate"
            break
        fi
    done
    if [ "$py" = "" ]; then
        echo "steam-vkb: no python interpreter found" >&2
        exit 1
    fi
    exec "$py" -m steam_vkb "$@"
fi

export PYTHONPATH="$prefix/libexec${PYTHONPATH:+:$PYTHONPATH}"
exec "$prefix/venv/bin/python" -m steam_vkb "$@"
