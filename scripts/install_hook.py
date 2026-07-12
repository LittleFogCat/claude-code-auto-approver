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

    We deliberately do NOT prefer ``pythonw.exe`` here, even though
    it would suppress the console window on its own. ``pythonw.exe``
    is a GUI-subsystem binary whose stdout does not reliably reach
    Claude Code over the pipe it uses to read the Decision JSON, so
    using it would break the hook protocol.

    Instead, the black-box suppression is handled by
    ``scripts/run_hidden.vbs``: the VBScript uses
    ``WScript.Shell.Run`` with ``WindowStyle=0`` (SW_HIDE), which
    hides the spawned process's console window even when the child
    is a console-subsystem binary like ``python.exe``.

    This is the same belt-and-braces pattern used by
    ``D:/code/python/nonewindowcli/run_hidden.vbs`` -- the
    difference is that nonewindowcli's demo writes to a file (no
    stdout pipe), while the hook MUST keep stdout working.
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

    Wraps the Python launch in ``scripts/run_hidden.vbs`` so the spawned
    process never shows a console window: ``wscript.exe`` (the VBScript host)
    is GUI-subsystem and the VBScript uses ``WScript.Shell.Run`` with
    ``WindowStyle=0`` (SW_HIDE).

    The command is a flat token list. The VBScript joins those tokens with
    quoted spaces, which keeps the round-trip
    ``settings.json -> shell -> wscript.exe -> WScript.Arguments ->
    WScript.Shell.Run`` robust against paths that contain spaces (the
    project venv and source paths almost always do on Windows).

    The :mod:`classifier.bridge.quiet_runner` module is still invoked to
    redirect ``sys.stderr`` to NUL 鈥?it's the belt-and-braces fallback in
    case the VBScript host itself ever emits something to its own stderr on
    a startup error path.
    """
    py = str(python_exe)
    vbs = str(REPO_ROOT / "scripts" / "run_hidden.vbs")
    return f'wscript.exe //nologo "{vbs}" "{py}" -m classifier.bridge.quiet_runner'


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

