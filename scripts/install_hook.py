"""Install PreToolUse hook into ~/.claude/settings.json (cross-platform).

Idempotent: removes any prior classifier-managed entries before re-installing.

Uses the project's .venv python (pythonw on Windows / pythonw3 on POSIX) so
the hook:
  - runs without allocating a console window (no cmd flash)
  - picks up the venv where classifier + uvicorn + fastapi are installed
  - doesn't need any vbs/cmd/sh wrapper to set PYTHONPATH

Env vars:
  CLF_CLAUDE_SETTINGS  override the target settings.json path
  CLF_HOOK_TIMEOUT     hook timeout in seconds (default 60)
  CLF_PY_EXE           override the python interpreter used by the hook
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = Path(
    os.environ.get("CLF_CLAUDE_SETTINGS")
    or (Path.home() / ".claude" / "settings.json")
)
HOOK_TIMEOUT = int(os.environ.get("CLF_HOOK_TIMEOUT", "60"))


def _venv_python() -> Path | None:
    """Return the project's .venv python interpreter, if present.

    We use the console-subsystem ``python.exe`` on Windows (not
    ``pythonw.exe``): Claude Code runs the hook via a hidden-console
    Git Bash, and a console child of that bash inherits the hidden
    console -- no window is ever shown.
    """
    candidates = [
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        REPO_ROOT / ".venv" / "bin" / "python3",         # POSIX
        REPO_ROOT / ".venv" / "bin" / "python",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _hook_command(python_exe: Path) -> str:
    """Build the shell command Claude Code runs for each PreToolUse event.

    Claude Code executes hook commands through Git Bash with
    ``windowsHide: true`` -- i.e. the bash process already owns a HIDDEN
    console. A console-subsystem child launched directly from that bash
    inherits the hidden console and allocates no window of its own.

    Do NOT reintroduce a ``wscript.exe``/``run_hidden.vbs`` wrapper or
    ``pythonw.exe``: the .venv scripts are uv trampolines, and the
    ``pythonw.exe`` trampoline spawns the BASE ``python.exe``
    (console subsystem) from a GUI-subsystem parent that owns no
    console -- so Windows allocates a brand-new console for it, which
    Win11 hands to Windows Terminal and the user sees a Terminal
    window flash on every single tool call.

    The :mod:`classifier.bridge.quiet_runner` module stays in the
    chain as belt-and-braces: it redirects ``sys.stderr`` (and a
    broken ``sys.stdout``) to NUL before importing the bridge, in case
    the interpreter is ever launched without an inherited stderr pipe.
    """
    py = str(python_exe)
    return f'"{py}" -m classifier.bridge.quiet_runner'


def main() -> int:
    override = os.environ.get("CLF_PY_EXE")
    if override:
        python_exe = Path(override)
    else:
        found = _venv_python()
        if found is None:
            print(
                "FATAL: no .venv python found. Either create one "
                "(`python -m venv .venv && pip install -e .`) or set CLF_PY_EXE.",
                file=sys.stderr,
            )
            return 2
        python_exe = found

    hook_command = _hook_command(python_exe)

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text("{}\n", encoding="utf-8")

    with SETTINGS_FILE.open("r", encoding="utf-8") as f:
        settings = json.load(f) or {}

    hooks = settings.setdefault("hooks", {})
    pre = hooks.get("PreToolUse", []) or []

    def _is_classifier_entry(entry: dict) -> bool:
        # Match the _classifier sentinel OR any hook whose command
        # mentions our bridge module. The second rule catches hand-
        # edited entries that lack the sentinel.
        if entry.get("_classifier"):
            return True
        for h in entry.get("hooks", []) or []:
            cmd = (h.get("command") or "")
            if "classifier.bridge" in cmd:
                return True
        return False

    pre = [h for h in pre if not _is_classifier_entry(h)]

    pre.append(
        {
            "matcher": ".*",
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command,
                    "timeout": HOOK_TIMEOUT,
                }
            ],
            "_classifier": True,
        }
    )
    hooks["PreToolUse"] = pre

    # Atomic write so a crash mid-edit doesn't corrupt settings.json.
    fd, tmp = tempfile.mkstemp(
        prefix=".settings_", suffix=".json.tmp", dir=str(SETTINGS_FILE.parent)
    )
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    print(f"installed hook in {SETTINGS_FILE}")
    print(f"command:    {hook_command}")
    print(f"timeout:    {HOOK_TIMEOUT}s")
    print()
    print("Current PreToolUse hooks:")
    print(json.dumps(hooks["PreToolUse"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

