"""hook_bridge.py - thin stdin->HTTP->stdout wrapper for Claude Code hooks.

Responsibilities:
1. Read a PreToolUse JSON event from stdin.
2. POST it to the local classifier service.
3. Write the Decision JSON to stdout.

It also handles:
- Auto-start: if the service is not reachable, try to launch it in the
  background (best-effort), then retry the request once it's healthy.
- Concurrency lock: only one bridge at a time will attempt the auto-start.
- Auth header injection if CLF_BRIDGE_TOKEN is set.
- Fail-open: if we cannot reach the service even after auto-start, return
  exit code 0 (allow) and a JSON decision on stdout that records the failure.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = os.environ.get("CLF_CLASSIFIER_URL", "http://127.0.0.1:8765/classify")
HEALTH_URL = ENDPOINT.replace("/classify", "/health")
TOKEN = os.environ.get("CLF_BRIDGE_TOKEN", "")
START_TIMEOUT_S = float(os.environ.get("CLF_BRIDGE_START_TIMEOUT_S", "8"))
REQUEST_TIMEOUT_S = float(os.environ.get("CLF_BRIDGE_REQUEST_TIMEOUT_S", "50"))

# Lockfile used so only one bridge starts the service per host.
# Default to repo-local .run/ so we never need ~/.config write permission.
_DEFAULT_LOCK = Path(__file__).resolve().parents[3] / ".run" / "bridge.lock"
_LOCK_DIR = Path(os.environ.get("CLF_BRIDGE_LOCK_DIR", str(_DEFAULT_LOCK.parent)))
_LOCK_PATH = Path(os.environ.get("CLF_BRIDGE_LOCK_PATH", str(_DEFAULT_LOCK)))


def _is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_host_port(url: str) -> tuple[str, int]:
    # url like http://127.0.0.1:8765/classify
    try:
        from urllib.parse import urlparse

        u = urlparse(url)
        host = u.hostname or "127.0.0.1"
        port = u.port or (443 if u.scheme == "https" else 80)
        return host, port
    except Exception:  # noqa: BLE001
        return "127.0.0.1", 8765


def _health_ok(timeout: float = 0.8) -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001
        return False


def _try_acquire_lock(timeout_s: float = 0.0) -> bool:
    """Best-effort inter-process lock via filesystem mtime.

    Returns True if we acquired it (or someone else is already trying and we
    decided to skip). False if we should proceed to spawn.
    """
    try:
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return True
    try:
        if _LOCK_PATH.exists():
            age = time.time() - _LOCK_PATH.stat().st_mtime
            if age < 30:  # another bridge is actively starting
                return False
        _LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return True


def _release_lock() -> None:
    try:
        if _LOCK_PATH.exists() and _LOCK_PATH.read_text(encoding="utf-8") == str(os.getpid()):
            _LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _spawn_service() -> None:
    """Best-effort: launch uvicorn in the background and detach.

    Launch goes via ``subprocess.Popen`` with the Win32
    ``CREATE_NO_WINDOW`` flag, using the plain console-subsystem
    ``python.exe`` (NOT ``pythonw.exe``). The .venv executables are uv
    trampolines: the ``pythonw.exe`` trampoline is GUI-subsystem and
    spawns the BASE ``python.exe`` (console) with no console to
    inherit, so Windows allocates a brand-new console for it -- on
    Win11 the default-terminal handoff pops a Windows Terminal window
    that flashes on screen. With the console ``python.exe`` trampoline
    plus CREATE_NO_WINDOW, the trampoline gets a hidden console and
    the base interpreter simply inherits it.

    Windows never kills a child when its parent exits, so no
    DETACHED_PROCESS flag is needed (and it must not be combined with
    CREATE_NO_WINDOW anyway).
    """
    host, port = _parse_host_port(ENDPOINT)
    log_path = Path(os.environ.get("CLF_BRIDGE_SERVICE_LOG", str(Path(__file__).resolve().parents[3] / "logs" / "service.log")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab", buffering=0)

    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    argv = [
        sys.executable, "-m", "uvicorn", "classifier.main:app",
        "--host", host, "--port", str(port), "--log-level", "info",
    ]

    try:
        subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=log_fp,
            close_fds=True,
            creationflags=flags,
        )
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[bridge] failed to spawn service: {e}\n")


def _ensure_service_running() -> None:
    """Make sure the classifier service is healthy. Auto-start if not."""
    host, port = _parse_host_port(ENDPOINT)
    if _is_port_open(host, port) and _health_ok():
        return
    if not _try_acquire_lock():
        # Another bridge is starting; wait for the lock to clear / health to come up.
        deadline = time.time() + START_TIMEOUT_S
        while time.time() < deadline:
            if _health_ok():
                return
            time.sleep(0.3)
        return

    try:
        _spawn_service()
        deadline = time.time() + START_TIMEOUT_S
        while time.time() < deadline:
            if _health_ok():
                return
            time.sleep(0.3)
    finally:
        _release_lock()


def _post_classify(payload: dict) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Bridge-Token"] = TOKEN

    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _fail_open_decision(reason: str) -> str:
    return json.dumps(
        {
            "decision": "approve",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            },
            "reason": reason,
        }
    )


def main() -> int:
    # Read stdin once. Be tolerant: Claude Code sends a single JSON document.
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[bridge] invalid JSON from claude: {e}\n")
        # Fail-open: don't block the user on a broken hook payload.
        sys.stdout.write(_fail_open_decision(f"bridge: invalid stdin JSON: {e}"))
        return 0

    # Ensure service is running (auto-start if not)
    try:
        _ensure_service_running()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[bridge] could not ensure service: {e}\n")
        sys.stdout.write(_fail_open_decision(f"bridge: service unavailable: {e}"))
        return 0

    # POST to /classify
    try:
        status, body = _post_classify(payload)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        sys.stderr.write(f"[bridge] classify request failed: {e}\n")
        sys.stdout.write(_fail_open_decision(f"bridge: request failed: {e}"))
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[bridge] unexpected error: {e}\n")
        sys.stdout.write(_fail_open_decision(f"bridge: unexpected: {e}"))
        return 0

    # Always echo back to Claude on stdout (it's how Claude Code reads the decision)
    sys.stdout.write(body if body else _fail_open_decision("bridge: empty response"))
    sys.stdout.flush()

    # Exit code 2 -> Claude Code surfaces the stderr to Claude.
    # We only do that for hard service errors; a normal deny uses the JSON.
    if status >= 500:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())