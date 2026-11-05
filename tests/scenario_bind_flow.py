"""Scenario runner: the full bind/activate/deactivate flow against FakeKwin.

Run under pytest as a *subprocess* on purpose:

1. pywayland calls back into Python through cffi ``extern`` entry points,
   which are only safe to invoke on the thread that imported the module
   (pywayland's own tests run the server on the importing thread).
2. tearing a pywayland server and client down inside one interpreter
   segfaults during garbage collection on this pywayland version — a teardown
   artifact of the *test harness*, unrelated to the bridge, which in
   production is a plain single-client process.

The script prints machine-readable markers which the pytest wrapper parses:
``BIND <n>`` / ``SUMMON <n>`` / ``EVENTS <names>`` / ``RESULT OK|FAIL``.
"""

import os
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

SOCKET_NAME = "steam-vkb-scenario"
RUNTIME_DIR = "/tmp/svk-scenario-%s" % os.getpid()

os.environ["XDG_RUNTIME_DIR"] = RUNTIME_DIR
os.environ["WAYLAND_DISPLAY"] = SOCKET_NAME
os.environ.pop("WAYLAND_SOCKET", None)
os.makedirs(RUNTIME_DIR, exist_ok=True)

from steam_vkb.bridge import SteamVkbBridge  # noqa: E402
from steam_vkb.config import Config  # noqa: E402
from tests.fake_kwin import FakeKwin  # noqa: E402

SHUTDOWN_MS = 1600

# Flow mirrors KWin's behaviour:
#   bind (no active input) -> activate -> deactivate -> activate -> activate(dup)
steps = []
server = FakeKwin()
for label, delay, action in (
    ("bind-verify", 300, "show"),
    ("first-activate", 500, "show"),
    ("deactivate", 700, "hide"),
    ("second-activate", 900, "show"),
    ("duplicate-activate", 1000, "show"),
):
    del label

events_lock = threading.Lock()
summons: list[str] = []


def summon(config) -> bool:
    with events_lock:
        summons.append("summon")
    return True


cfg = Config(open_cmd=[":invalid-command-for-test:"], debug=False)


def show():
    server.show_input()


def hide():
    server.hide_input()


def terminate():
    server.step_terminate()


steps = [
    (400, show),
    (600, hide),
    (800, show),
    (900, show),  # duplicate while open -> the bridge's debounce must not re-summon
    (1200, terminate),
]

server_thread = threading.Thread(target=server.start, args=(steps, SOCKET_NAME), daemon=True)
server_thread.start()

bridge_result: dict[str, object] = {}


def run_bridge() -> None:
    bridge = SteamVkbBridge(cfg, summoner=summon)
    bridge_result["exit"] = bridge.run()


bridge_thread = threading.Thread(target=run_bridge, daemon=True)
bridge_thread.start()

deadline = time.time() + 5.0
while time.time() < deadline and len(summons) < 2:
    time.sleep(0.01)

server_thread.join(6)
bridge_thread.join(6)

# Guards before verdict: server publish / bind accounting
publish_ok = server.bind_count == 1
events_ok = server.events_sent == ["activate", "deactivate", "activate", "activate"]
summon_ok = len(summons) == 2

print("BIND %d" % server.bind_count, flush=True)
print("SUMMON %d" % len(summons), flush=True)
print("EVENTS %s" % (",".join(server.events_sent),), flush=True)
if publish_ok and events_ok and summon_ok:
    print("RESULT OK", flush=True)
else:
    print("RESULT FAIL", flush=True)
    os._exit(1)
os._exit(0)
