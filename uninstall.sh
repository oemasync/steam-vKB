#!/bin/sh
# Remove a system or --user installation (same scope as install.sh's arg).
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
user_mode=0
[ "${1:-}" = "--user" ] && user_mode=1

if [ "$user_mode" = 1 ]; then
    prefix="${XDG_DATA_HOME:-$HOME/.local/share}/steam-vkb"
    apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
else
    prefix="/opt/steam-vkb"
    apps_dir="/usr/share/applications"
    if [ "$(id -u)" -ne 0 ]; then
        echo "uninstall.sh: system uninstall needs root (or use: $0 --user)" >&2
        exit 1
    fi
fi

rm -rf -- "$prefix"
[ -f "$apps_dir/steam-vkb.desktop" ] && rm -f -- "$apps_dir/steam-vkb.desktop"
if [ "$user_mode" = 0 ]; then
    [ -f /usr/bin/steam-vkb ] && rm -f -- /usr/bin/steam-vkb
fi

for sy in kbuildsycoca6 kbuildsycoca5; do
    if command -v "$sy" >/dev/null 2>&1; then
        "$sy" --noincremental >/dev/null 2>&1 || true
        break
    fi
done
echo "==> steam-vkb removed. Reset via System Settings -> Virtual Keyboard."
echo "    (Stock fallback: pick 'Plasma Keyboard'; or kwriteconfig6 --file kwinrc"
echo "     --group Wayland --key InputMethod /usr/share/applications/org.kde.plasma.keyboard.desktop)"
