"""Quiet entry point: silence stderr (and a broken stdout) before importing
the hook bridge.

This exists because of a long-standing Win32 / Pythonw quirk: when a
GUI-subsystem Python (``pythonw.exe``) is launched without an inherited
stderr handle -- which is exactly the case when Claude Code forks it as
a hook -- the first ``sys.stderr.write`` call causes the interpreter to
allocate a brand-new ``cmd.exe``-style console window to display the
error. That console stays on screen until the process exits and the
user dismisses it (or it's closed when the script finishes).

Foreground-from-tray flashing isn't the failure mode here -- the box
sticks around. The fix is to make sure ``sys.stderr`` is a real sink
(NUL) BEFORE we import anything that might log on the failure paths
(fail-open / invalid JSON / classify error / spawn failure).

Same belt-and-braces treatment for stdout: if it isn't attached to a
parent pipe, redirect it to NUL too -- otherwise uvicorn's first
log line via ``print()`` will do the same trick when auto-spawning.
"""
from __future__ import annotations

import os
import sys

_NULL = open(os.devnull, "w", encoding="utf-8")

# stderr: always redirect -- when pythonw ran without an inherited stderr
# handle this is what was making the box appear.
sys.stderr = _NULL


def _try_flush(stream) -> bool:
    try:
        stream.flush()
        return True
    except (ValueError, OSError):
        return False


# stdout: only flip it if it isn't actually attached. When Claude Code
# passes a stdout pipe, sys.stdout is fine and we want to keep that.
if not _try_flush(sys.stdout):
    sys.stdout = _NULL

# Now safe -- no further console allocation can be triggered.
from classifier.bridge.hook_bridge import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
