# steam-vKB — Bazzite/SteamOS Game Mode on-screen keyboard in desktop mode

Turn the Steam "Game Mode" (deck) on-screen keyboard into a first-class option
inside Plasma desktop mode's virtual keyboard selector, next to
"Plasma Keyboard" and "Maliit":

```
System Settings -> Keyboard -> Virtual Keyboard -> "Steam Game Mode Keyboard"
```

Everything here is plain userspace: KWin stays untouched, and on Bazzite the
Steam Keyboard window is already shaped like an overlay by the existing
``kwinrulesrc`` rules from Valve's presets.

## How desktop mode's virtual keyboard actually works (how we plug in)

Verified against KWin sources (``src/kcms/virtualkeyboard/kcmvirtualkeyboard.cpp``,
``src/inputmethod.cpp``, ``src/wayland/inputmethod_v1.cpp``) and the KWin
Maliit-era docs:

1. The *Virtual Keyboard* KCM lists every desktop entry in
   ``/usr/share/applications`` carrying ``X-KDE-Wayland-VirtualKeyboard=true``
   (plus a "None" row).  That is the entire discovery mechanism - any
   application can register as a virtual keyboard.
2. Selecting an entry makes KWin spawn that entry's ``Exec`` and hand it a
   *private Wayland socket* via ``WAYLAND_SOCKET`` (KWin unsets CLOEXEC for
   the child).  The spawned process is the compliant input method: it must
   attach to that socket and speak ``zwp_input_method_unstable_v1``.
3. KWin publishes a ``zwp_input_method_v1`` global on that connection.  When
   any app's text input gains focus, KWin sends ``activate`` (new id
   ``zwp_input_method_context_v1``) - retroactively right on ``bind`` if a
   text field is already active.
4. An input method *may* render its own panel surface and *may* grab the
   hardware keyboard.  It does not have to: hardware keys keep flowing if it
   never grabs, and clicks land wherever the windows are.

So "an option in the desktop virtual keyboard" == "a small IM-bridge process
behind a properly-marked desktop entry".  That is all steam-vkb is.

## How the Steam Game Mode keyboard is summoned

* ``steam steam://open/keyboard`` opens the deck-style keyboard overlay from
  the running Steam client.  This is the documented SDL/gamescope URL (see
  the SDL wiki keyboard docs and gamescope issue #668's overlay invocation),
  and it works outside Game Mode as long as Steam is running - it is what
  SteamOS desktop mode's own "Steam Keyboard" window is.
* Steam types into the focused application through its virtual input device
  (Bazzite's ``inputplumber``/`deck-uhid keyboard` targets do this), so the
  bridge does not need to synthesise ``commit_string``/``keysym`` traffic.
* The bridge is *stateless* about text: it only maps IM activation events to
  "summon the Steam keyboard", debounced.  It never grabs ``grab_keyboard``,
  so typing on a physical keyboard is unaffected while the overlay is open.

The wallpaper/etc. window behavior ("stays above, skips taskbar") is already
provided by Bazzite/Vapor's ``kwinrulesrc`` for a window titled "Steam
Keyboard" with class ``steamwebhelper`` (see
``spec_files/steamdeck-kde-presets/0001-steam-virtual-keyboard.patch``).

## Repository layout

| Path | What it is |
|---|---|
| ``data/steam-vkb.desktop`` | The KCM-listed desktop entry (``X-KDE-Wayland-VirtualKeyboard=true``) |
| ``data/steam-vkb.sh`` | Launcher: resolves the steam-vkb venv, execs the bridge module |
| ``src/steam_vkb/`` | The bridge: config, opener, wayland input-method client |
| ``install.sh`` / ``uninstall.sh`` | venv-based install (system or ``--user``) incl. kbuildsycoca cache refresh |
| ``packaging/steam-vkb.spec`` | Experimental RPM recipe for image-side layering |
| ``tests/`` | Offline integration harness: fake KWin over a real unix socket |
| ``docs/DESIGN.md`` | Longer design notes + pointers used while building |

## Install

```sh
./install.sh          # system-wide: /opt/steam-vkb + /usr/bin/steam-vkb + desktop entry
./install.sh --user   # ~/.local/share/steam-vkb + user applications dir
```

Requires ``python3`` (with ``venv``), one network fetch from PyPI to pin
``pywayland==0.4.19`` (the only runtime dependency - it ctypes-libwayland,
which any Plasma system already has), and a Plasma Wayland session running
KWin with the Virtual Keyboard KCM (Plasma 5.17+; current Bazzite/Fedora are
fine).

## Use

1. Install (above).
2. System Settings -> Keyboard -> Virtual Keyboard -> select **Steam Game
   Mode Keyboard**.
3. Tap a text field; the Hunt mode keyboard pops with Steam's deck
   keyboard.  Dismiss via its own control (see Known limits).

Tuning (environment variables the launcher passes through, all optional):

| Var | Meaning |
|---|---|
| ``STEAM_VKB_OPEN`` | override the summon command, e.g. ``xdg-open 'steam://open/keyboard'`` |
| ``STEAM_VKB_CLOSE`` | command tried when deactivating (only if close-on-deactivate on) |
| ``STEAM_VKB_CLOSE_ON_DEACTIVATE`` | ``1`` to attempt dismissal when the text field loses focus (off by default) |
| ``STEAM_VKB_DEBUG`` | ``1`` logs activation/deactivation to stderr (journal through KWin) |
| ``STEAM_VKB_PREFIX`` | alternative install prefix with ``venv/bin/python`` |

## Known limits (honest ledger)

* Steam desktop client must be running (Bazzite autostarts it; the first
  summon launches it otherwise).
* Auto-show fires when applications *commit* Wayland text-input state
  (``zwp_text_input_v1/v2/v3``).  Qt, GTK-6 and Chromium-based apps do; some
  X11-only apps will not trigger it (KWin routes these through its own
  internal text-input glue, results vary).  Steam's own keyboard can also
  still be summoned manually through Steam's shortcuts at any time.
* No auto-dismiss: we never grab the hardware keyboard and never render a
  panel, so we also do not clip the Steam window; it hides with its own
  close control.  ``STEAM_VKB_CLOSE_ON_DEACTIVATE=1`` attempts a dismiss
  command on deactivate but Steam has no documented close URL - treat it as
  experimental.
* Multi-monitor geometry: the Steam keyboard does not follow the focused
  text field's position on screen (the ``steam://open/keyboard`` URL's
  position parameters are gamescope-only per the SDL wiki).

## Verification status

* Offline harness (this repo): the bridge's real client path - connect via
  the dedicated IM socket, registry enumeration, ``zwp_input_method_v1``
  bind, KWin's activate-with-buffered-state pacing, activate/deactivate
  state machine, summon debounce, and the strip-KWin-env command spawning -
  is exercised against a fake KWin (pywayland server standing in for KWin,
  mirroring pywayland's own server-side tests).  ``pytest -q``: 6/6.
* On-device smoke test (real KWin session, real Steam client): **pending**
  on a Bazzite box; checklist is in ``docs/DESIGN.md``.

## Credit / provenance

* KWin virtual keyboard KCM + input-method-v1 server behaviour: KDE KWin
  sources (GPL), consulted for the integration contract.
* ``X-KDE-Wayland-VirtualKeyboard=true`` discovery: openSUSE Wayland input
  methods SDB and KWin's KCM implementation.
* ``steam://open/keyboard``: SDL wiki / gamescope overlay usage.
* The Bazzite ``steamdeck-kde-presets`` KWin rules patch for the "Steam
  Keyboard" window shape.
