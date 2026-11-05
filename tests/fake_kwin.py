"""Fake KWin: a pywayland-server stand-in for KWin's input-method publisher.

Stands in for KWin over the dedicated input-method connection:

* publishes a ``zwp_input_method_v1`` global (KWin ``inputmethod_v1.cpp``:
  ``InputMethodV1InterfacePrivate`` publishes ``zwp_input_method_v1`` with
  ``s_version = 1``);
* on bind sends ``activate``(new_id context) immediately if a text input is
  "already active" (mirrors KWin ``zwp_input_method_v1_bind_resource``), and
  otherwise waits for the test to call ``show_input``/``hide_input``;
* after activation it mirrors KWin's buffered-state handling: surrounding_text,
  preferred_language, commit_state.

The pywayland server API is used the same way pywayland's own
test/test_registry_bind.py uses it (proven repeatedly in this repo's probe
scripts), so the bridge's real client path (connect, registry, bind, event
dispatch, proxy materialisation) is exercised over a genuine unix socket.
"""

from __future__ import annotations

from pywayland import ffi, lib
from pywayland.protocol import input_method_unstable_v1 as im_v1
from pywayland.server import Display as ServerDisplay

PROTOCOL_VERSION = 1
EVENT_ACTIVATE = 0
EVENT_DEACTIVATE = 1


class FakeKwin:
    """Fake KWin input-method publisher; run the server, then drive the flow.

    Run ``start(steps, socket_name)`` ON THE MAIN THREAD (keepalive for the
    cffi extern callbacks).  ``steps`` is a list of ``(delay_ms, func)``
    single-shot timers executed on the server event-loop thread in schedule
    order; a final ``discard`` step usually terminates the display (handled
    internally via ``shutdown_ms``).
    """

    def __init__(self) -> None:
        self.display = ServerDisplay()
        self._bound_resource = None
        self._active_context = None
        self.bind_count = 0
        self.events_sent: list[str] = []
        self.client_requests: list[tuple[str, object]] = []
        self.initially_active = False
        self.keepalive: list[object] = []

    # -- lifecycle -----------------------------------------------------------
    def start(self, steps: list[tuple[int, object]], socket_name: str, shutdown_ms: int = 1500) -> None:  # type: ignore[override]
        self.display.add_socket(socket_name)
        self.kbd_global = im_v1.ZwpInputMethodV1.global_class(self.display, PROTOCOL_VERSION)
        self.kbd_global.bind_func = self._on_bind
        self.keepalive.append(self.kbd_global)

        loop = self.display.get_event_loop()
        for delay_ms, func in steps:
            source = loop.add_timer(lambda _data, fn=func: (fn(), 0)[1], data=None)
            source.timer_update(delay_ms)
        exit_source = loop.add_timer(
            lambda _data: (self.display.terminate(), 0)[1], data=None
        )
        exit_source.timer_update(shutdown_ms)

        self.display.run()  # blocks until terminate()
        self.display.destroy()

    def step_terminate(self) -> None:
        self.display.terminate()

    # -- KWin behaviour ------------------------------------------------------
    def _on_bind(self, resource) -> None:  # noqa: ANN001
        self.bind_count += 1
        self._bound_resource = resource
        self.keepalive.append(resource)
        if self.initially_active:
            self.show_input()

    def show_input(self) -> None:
        assert self._bound_resource is not None, "no client has bound the input method yet"
        bound = self._bound_resource
        client_ptr = lib.wl_resource_get_client(bound._ptr)
        ctx = im_v1.ZwpInputMethodContextV1.resource_class(client_ptr, PROTOCOL_VERSION)
        self.keepalive.append(ctx)
        ctx.dispatcher["commit_string"] = self._on_client_commit
        self._active_context = ctx
        _post_object_event(bound, EVENT_ACTIVATE, ctx)
        self.events_sent.append("activate")
        ctx.surrounding_text("", 0, 0)
        ctx.preferred_language("")
        ctx.commit_state(self._serial())

    def hide_input(self) -> None:
        if self._active_context is None or self._bound_resource is None:
            return
        _post_object_event(self._bound_resource, EVENT_DEACTIVATE, self._active_context)
        self._active_context = None
        self.events_sent.append("deactivate")

    def _on_client_commit(self, proxy, serial, text) -> None:  # noqa: ANN001
        self.client_requests.append(("commit_string", text))

    def _serial(self) -> int:
        current = getattr(self, "_serial_value", 100)
        self._serial_value = current + 1
        return self._serial_value


def _post_object_event(resource, opcode: int, obj_resource) -> None:
    """Post an event whose only argument is the pre-created server resource.

    libwayland server-side marshalling serialises ``o``/``n`` arguments by the
    wl_resource pointer (``wl_argument.o``); the resource must already exist.
    """
    args = ffi.new("union wl_argument[]", 1)
    args[0].o = ffi.cast("struct wl_object *", obj_resource._ptr)
    lib.wl_resource_post_event_array(resource._ptr, opcode, args)
