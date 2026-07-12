"""Integration test for hook_bridge.py against the live FastAPI app.

Spawns uvicorn in a background thread on a free port and POSTs through the
bridge script using subprocess.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(url: str, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.8) as r:
                if 200 <= r.status < 300:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


@pytest.mark.slow
def test_bridge_end_to_end(tmp_path):
    port = _free_port()
    host = "127.0.0.1"
    log_path = tmp_path / "svc.log"
    log_fp = open(log_path, "wb")

    # Start uvicorn
    # Write a clean user rules config so the subprocess loads R-001..R-003.
    cfg = tmp_path / 'rules.yaml'
    cfg.write_text('rules:\n  - id: R-001\n    type: denylist_cmd\n    priority: 10\n    severity: critical\n  - id: R-002\n    type: sensitive_path\n    priority: 10\n    severity: high\n  - id: R-003\n    type: branch_protect\n    priority: 20\n    severity: high\n', encoding='utf-8')

    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "classifier.main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO_ROOT),
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "CLF_RULES_FILE": str(cfg),
            "CLF_BEHAVIOR_ENABLE_CLAUDE_FALLBACK": "false",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )

    try:
        health_url = f"http://{host}:{port}/health"
        classify_url = f"http://{host}:{port}/classify"

        assert _wait_healthy(health_url), f"service did not become healthy. log: {log_path.read_text(errors='replace')}"

        # 1. Direct hit (no bridge)
        req = urllib.request.Request(
            classify_url,
            data=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["decision"] == "block"
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert body["matched_rule"]["id"].startswith("R-001")

        # 2. Hit through the bridge subprocess
        env = {
            **os.environ,
            "CLF_CLASSIFIER_URL": classify_url,
            "PYTHONPATH": str(REPO_ROOT / "src"),
        }
        bridge = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "classifier.bridge.hook_bridge"],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hi"}}).encode(),
            capture_output=True,
            env=env,
            timeout=15,
        )
        assert bridge.returncode == 0, bridge.stderr.decode()
        out = json.loads(bridge.stdout.decode())
        assert out["decision"] == "approve"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


import os  # noqa: E402