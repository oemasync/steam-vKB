# Design notes / decisions ledger

## Contract research receipts (what was checked against real sources)

* KCM candidate discovery - ``src/kcms/virtualkeyboard/kcmvirtualkeyboard.cpp``:
  ``m_services = KApplicationTrader::query(service -> service->property<bool>(
  "X-KDE-Wayland-VirtualKeyboard"))``; a "None" row is prepended.
* KWin spawn + private socket - ``src/inputmethod.cpp`` ``startInputMethod()``:
  ``QProcessEnvironment environment = kwinApp()->processStartupEnvironment()``,
  then ``environment.insert("WAYLAND_SOCKET", ...)`` +
  ``environment.insert("QT_QPA_PLATFORM", "wayland")`` +
  ``environment.insert("MALIIT_ENABLE_ANIMATIONS", "0")``, fd unsets CLOEXEC in
  the child, crashes restart up to 5x; clean exit = no restart
  (``stopInputMethod()`` terminate/kill on disable).
* Server-side global - ``src/wayland/inputmethod_v1.cpp``: KWin publishes
  ``zwp_input_method_v1`` with ``s_version = 1``; ``bind_resource`` immediately
  pushes retro-activate when a context exists
  (``zwp_input_method_v1_bind_resource`` -> ``send_activate``).
  **Important nuance:** upstream wayland-protocols' current
  ``unstable/input-method/input-method-unstable-v1.xml`` does not declare
  ``zwp_input_method_manager_v1``; KWin's model is bind-then-push.  Our client
  therefore binds ``zwp_input_method_v1`` and reacts to ``activate``/
  ``deactivate`` - exactly what pywayland's vendored generated module offers.
* Buffered text state - KWin ``sendActivate()`` follows the activate event with
  surrounding text / language / commit_state; harmless to ignore since we do
  not compose text.
* Steam summon URL - SDL wiki (keyboard) documents
  ``steam://open/keyboard``; gamescope issue #668 shows the URL with optional
  ``?Mode=&XPosition=...`` used by gamescope/SDL in Game Mode for in-game
  positioning (geometry params are gamescope-only).
* Bazzite's existing keyboard side files:
  - ``spec_files/steamdeck-kde-presets/0001-steam-virtual-keyboard.patch``
    shapes the "Steam Keyboard" window (keep-above, skip-taskbar, focus
    rule ``acceptfocusrule=2``, type 16, classes ``steamwebhelper steam``).
  - ``system_files/deck/shared/usr/share/ublue-os/just/85-bazzite-image.just``
    ``restore-virtual-keyboard`` sets ``kwinrc [Wayland]
    InputMethod=/usr/share/applications/org.kde.plasma.keyboard.desktop``
    (Plasma keyboard), i.e. the same config knob this project's entry uses.
* History of the keyboard back-and-forth in Bazzite git (commits 3d1a2727
  "Remove Maliit from System Settings on deck builds", 8afc8d28 "Remove
  maliit keyboard stuff breaking deck builds", 1f9dcda6 "functional Steam
  keyboard" KWin rules fix, 328e2437 "restore Plasma virtual keyboard"
  Plasma 6.x Maliit deprecation): the Steam Keyboard in desktop mode has
  always been reachable, just not *as a virtual keyboard option*.

## Why the bridge is minimal (no panel, no grab)

KWin's input method plumbing supports IM clients that render their own panel
(``zwp_input_panel_v1``) - Maliit does that.  steam-vkb deliberately does not:

* Steam's window is a real session window with a cursor-accurate target; a
  fake panel would only fight it.
* ``grab_keyboard`` exists so IMs can pre-edit text; we do not compose text.
  Not grabbing keeps hardware typing live even while the overlay is open.

## Harness notes (why the integration test is a subprocess)

* pywayland extern callbacks (``@ffi.def_extern``) are invoked by libwayland
  from arbitrary threads; the safe, proven pattern (pywayland's own
  ``test_registry_bind.py``) is *server on the importing thread*.
* pywayland 0.4.19 teardown segfaults under GC when a server and client share
  an interpreter; scenario runs in its own process and prints markers
  (``BIND/SUMMON/EVENTS/RESULT``) that the pytest wrapper asserts.

## On-device smoke checklist (pending)

1. ``install.sh`` on Bazzite; KCM shows "Steam Game Mode Keyboard"; select it,
   Apply.
2. Tap the browser search bar in desktop mode -> deck keyboard overlay over
   Plasma window (window rule keeps it above).
3. Type -> characters land in the focused app (via Steam's virtual device).
4. Hardware keyboard still types while overlay is open (no grab).
5. ``journalctl --user -u plasma-kwin_wayland`` shows no IM crash loop.
6. Re-select Plasma keyboard -> plasma-keyboard still restores.
