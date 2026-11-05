import collections
import os
import subprocess
import sys
import threading
import time
from typing import Optional

SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRC_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402

from steam_vkb.bridge import SteamVkbBridge  # noqa: E402
from steam_vkb.config import Config, KWIN_IM_ENV_KEYS, sanitize_env  # noqa: E402

from tests.fake_kwin import FakeKwin  # noqa: E402

SOCKET_NAME = "steam-vkb-test"


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[time.monotonic] = []

    def __call__(self, config):
        with self.lock:
            self.events.append(time.monotonic())
        return True

    @property
    def count(self) -> int:
        with self.lock:
            return len(self.events)


class CallCollector:
    """Serialised (thread-safe) log of label assignments."""

    def __init__(self):
        self.lock = threading.Lock()
        self.items: list[tuple[str, object]] = []

    def append(self, label, value=None):
        with self.lock:
            self.items.append((label, value))

    def labels(self) -> list[str]:
        with self.lock:
            return [label for label, _ in self.items]


@pytest.fixture()
def clean_wayland_env(monkeypatch):
    """Give the fake server and the client a fresh private runtime dir.

    Server runs on the *main thread* via FakeKwin.start (cffi extern
    callback limitation: extern entry points fire on the importing thread).
    """
    runtime_dir = "/tmp/svk-test-%s" % os.getpid()
    os.makedirs(runtime_dir, exist_ok=True)
    os.chmod(runtime_dir, 0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", runtime_dir)
    monkeypatch.setenv("WAYLAND_DISPLAY", SOCKET_NAME)
    monkeypatch.delenv("WAYLAND_SOCKET", raising=False)
    for key in KWIN_IM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield runtime_dir
    import shutil

    shutil.rmtree(runtime_dir, ignore_errors=True)


def _bridge_in_thread(cfg, recorder) -> tuple[threading.Thread, threading.Event]:
    finished = threading.Event()

    def run():
        try:
            SteamVkbBridge(cfg, summoner=recorder).run()
        finally:
            finished.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, finished


def test_bind_then_activate_deactivate_flow_scenario():
    """Full bind/activate/deactivate flow, run in its own process.

    The scenario subprocess owns a pywayland *server* (FakeKwin) and the
    bridge's real wayland *client* path.  It is a subprocess because a) the
    fake server's cffi extern callbacks are best served on the importing
    thread (see pywayland's own tests) and b) tearing a server + client down
    in one interpreter segfaults during GC on pywayland 0.4.19 - a harness
    teardown artifact; the product is a plain single-client process.
    """
    scenario = os.path.join(PROJECT_ROOT, "tests", "scenario_bind_flow.py")
    result = subprocess.run(  # noqa: S603
        [sys.executable, scenario],
        capture_output=True,
        text=True,
        timeout=60,
    )
    markers = {}
    for line in result.stdout.splitlines():
        if " " in line:
            key, _, value = line.partition(" ")
            markers.setdefault(key, value)
    assert markers.get("RESULT") == "OK", (
        f"scenario failed: {result.stdout!r} / stderr={result.stderr[-2000:]!r}"
    )
    assert markers.get("BIND") == "1", f"expected exactly one IM bind, got {markers.get('BIND')}"
    assert markers.get("SUMMON") == "2", f"expected two summons, got {markers.get('SUMMON')}"
    assert markers.get("EVENTS") == "activate,deactivate,activate,activate", (
        f"unexpected event log: {markers.get('EVENTS')}"
    )


def test_env_sanitization(clean_wayland_env, tmp_path):
    """Stripped wayland vars never reach the Steam child process."""
    from steam_vkb.opener import summon

    out_path = tmp_path / "child_env.json"
    child_script = "\n".join(
        [
            "import json, os",
            f"path = {str(out_path)!r}",
            "keys = ['WAYLAND_SOCKET', 'QT_QPA_PLATFORM', 'MALIIT_ENABLE_ANIMATIONS',"
            " 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'STEAM_VKB_OPEN']",
            "with open(path, 'w') as fh:",
            "    json.dump({k: os.environ.get(k) for k in keys}, fh)",
        ]
    )
    inner_env = dict(os.environ)
    inner_env["WAYLAND_SOCKET"] = "77"  # what KWin sets for the IM process
    inner_env["QT_QPA_PLATFORM"] = "wayland"

    assert summon([sys.executable, "-c", child_script], env=inner_env) is True
    deadline = time.time() + 5
    while not out_path.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert out_path.exists(), "child process never wrote its env dump"
    import json

    child_env = json.loads(out_path.read_text())
    assert child_env["WAYLAND_SOCKET"] is None, "the private IM socket must not leak to Steam"
    assert child_env["QT_QPA_PLATFORM"] is None, "KWin's forced QT platform must not leak to Steam"
    assert child_env["MALIIT_ENABLE_ANIMATIONS"] is None
    assert child_env["XDG_RUNTIME_DIR"], "session RT environment must be preserved for Steam"


def test_state_debounce_unit():
    from steam_vkb.bridge import _SummonState

    state = _SummonState()
    now = 10.0
    assert state.open_now(now) is True
    assert state.open_now(now + 0.01) is False  # debounce window swallow
    state.close()
    assert state.open_now(now + 0.2) is True  # closed -> open after close


def test_config_from_env():
    cfg = Config.from_env({})
    assert cfg.open_cmd is None
    assert cfg.close_on_deactivate is False

    cfg2 = Config.from_env(
        {
            "STEAM_VKB_OPEN": "steam 'steam://open/keyboard?Mode=0'",
            "STEAM_VKB_CLOSE_ON_DEACTIVATE": "true",
            "STEAM_VKB_DEBUG": "1",
        }
    )
    assert cfg2.open_cmd == ["steam", "steam://open/keyboard?Mode=0"]
    assert cfg2.close_on_deactivate is True
    assert cfg2.debug is True


def test_sanitize_env_strips_kwin_keys():
    env = {key: "lifted" for key in KWIN_IM_ENV_KEYS}
    env["DISPLAY_REMOTE"] = ":0"
    result = sanitize_env(env)
    for key in KWIN_IM_ENV_KEYS:
        assert key not in result
    assert result["DISPLAY_REMOTE"] == ":0"


def test_desktop_entry_carries_virtualkeyboard_marker():
    here = PROJECT_ROOT
    with open(os.path.join(here, "data", "steam-vkb.desktop")) as fh:
        content = fh.read()
    assert "X-KDE-Wayland-VirtualKeyboard=true" in content
    assert content.strip().splitlines()[0] == "[Desktop Entry]"
