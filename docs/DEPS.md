# Dependency manifest (pinned)

* Dev interpreter: `/root/.venvs/svkb-dev/bin/python` (durable venv, team
  doctrine: never install into pruned scratch).
* Runtime dependency: `pywayland==0.4.19` (pin identical to install.sh and
  the pytest scenario; pywayland is pure-Python + ctypes to
  `libwayland-client`).
* Test dependency: `pytest`.
* Protocol ground truth: wayland-protocols tag `1.45` XML
  (``unstable/input-method/input-method-unstable-v1.xml``) - matches
  pywayland's vendored generated module and KWin's server implementation.
* KWin behaviour ground truth: KDE KWin master sources (see docs/DESIGN.md).
