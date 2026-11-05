#!/bin/sh
# Install steam-vkb (system-wide by default; pass --user for a user install)
#
#   ./install.sh          # installs to /opt/steam-vkb + /usr/share/applications
#   ./install.sh --user   # installs to ~/.local/share/steam-vkb (desktop entry with it)
#
# Requires: python3 (with venv), network access to PyPI once (to pull the
# pinned pywayland wheel), a Plasma Wayland session with the Virtual Keyboard
# KCM (Plasma 5.17+; Fedora/Bazzite current is a given).
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYWAYLAND_PIN="0.4.19"

user_mode=0
[ "${1:-}" = "--user" ] && user_mode=1

if [ "$user_mode" = 1 ]; then
    prefix="${XDG_DATA_HOME:-$HOME/.local/share}/steam-vkb"
    apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
else
    prefix="/opt/steam-vkb"
    apps_dir="/usr/share/applications"
    if [ "$(id -u)" -ne 0 ]; then
        echo "install.sh: system install needs root (or use: $0 --user)" >&2
        exit 1
    fi
fi

echo "==> installing steam-vkb into $prefix"
mkdir -p "$prefix/libexec" "$prefix/venv"
cp -rv "$HERE/src/steam_vkb" "$prefix/libexec/"

if ! $prefix/venv/bin/python -c "import pywayland" >/dev/null 2>&1; then
    python3 -m venv "$prefix/venv"
    echo "==> installing pywayland $PYWAYLAND_PIN into the steam-vkb venv"
    "$prefix/venv/bin/pip" --quiet install "pywayland==$PYWAYLAND_PIN"
fi

if [ "$user_mode" = 1 ]; then
    install -D "$HERE/data/steam-vkb.sh" "$prefix/bin/steam-vkb"
    bin_dir="$prefix/bin"
else
    install -D -m 755 "$HERE/data/steam-vkb.sh" /usr/bin/steam-vkb
    bin_dir="/usr/bin"
fi

# Desktop entry: Exec must point at the launcher we just installed.
sed "s|^Exec=steam-vkb|Exec=$bin_dir/steam-vkb|" "$HERE/data/steam-vkb.desktop" \
    > "$apps_dir/steam-vkb.desktop"

# Install the KWin window rule that keeps the Steam keyboard (and our top bar)
# above other windows, matching Bazzite's steamdeck-kde-presets patch.
kwinrules_src="$HERE/data/kwinrulesrc"
if [ "$user_mode" = 1 ]; then
    kwinrules_dst="${XDG_CONFIG_HOME:-$HOME/.config}/kwinrulesrc"
else
    kwinrules_dst="/etc/xdg/kwinrulesrc"
fi
if [ -f "$kwinrules_dst" ]; then
    cp -a "$kwinrules_dst" "$kwinrules_dst.bak.steam-vkb" 2>/dev/null || true
fi
install -D -m 644 "$kwinrules_src" "$kwinrules_dst"
echo "==> installed kwinrules -> $kwinrules_dst"

# Make sure KWin actually uses our keyboard and pops it up on any focus
# (touch or mouse), including password fields.
kwrite=""
for kc in kwriteconfig6 kwriteconfig5; do
    if command -v "$kc" >/dev/null 2>&1; then kwrite="$kc"; break; fi
done
if [ "$user_mode" = 1 ]; then
    kwinrc_dst="${XDG_CONFIG_HOME:-$HOME/.config}/kwinrc"
    desktop_path="$apps_dir/steam-vkb.desktop"
else
    kwinrc_dst="/etc/xdg/kwinrc"
    desktop_path="$apps_dir/steam-vkb.desktop"
fi
if [ -n "$kwrite" ]; then
    "$kwrite" --file "$kwinrc_dst" --group Wayland --key InputMethod "$desktop_path" >/dev/null 2>&1 || true
    "$kwrite" --file "$kwinrc_dst" --group Wayland --key VirtualKeyboardEnabled true >/dev/null 2>&1 || true
    "$kwrite" --file "$kwinrc_dst" --group Wayland --key VirtualKeyboardMode 2 >/dev/null 2>&1 || true
fi

# Rebuild the desktop entry cache so the Virtual Keyboard KCM sees the new
# option immediately (kbuildsycoca6 falls back to kbuildsycoca5 automatically).
for sy in kbuildsycoca6 kbuildsycoca5; do
    if command -v "$sy" >/dev/null 2>&1; then
        echo "==> running $sy"
        "$sy" --noincremental >/dev/null 2>&1 || true
        break
    fi
done

echo "==> done. Next step:"
echo "    System Settings -> Keyboard -> Virtual Keyboard -> 'Steam Game Mode Keyboard'"
echo "    (takes effect after KWin restarts the virtual keyboard, i.e. Apply + focus)"
