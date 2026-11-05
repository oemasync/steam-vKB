import os
import sys

from .bridge import SteamVkbBridge, main

__all__ = ["SteamVkbBridge", "main"]

if __name__ == "__main__":
    # Hard-exit: pywayland 0.4.19 segfaults in interpreter shutdown after a
    # Display object is collected (known upstream teardown artifact).  A
    # SIGSEGV exit would read as CrashExit to KWin and feed its input-method
    # restart/crash counter even though the bridge finished cleanly.
    code = main()
    sys.stderr.flush()
    os._exit(code)
