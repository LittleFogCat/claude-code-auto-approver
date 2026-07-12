# Claude Code Classifier

A local **PreToolUse hook backend** for Claude Code. Sits between Claude Code
and the OS, decides whether each tool call should run, and blocks dangerous
ones automatically.

* **Deterministic first**: regex/path rules run in milliseconds.
* **Claude Haiku 4.5 fallback**: when rules do not match, Claude classifies the
  tool call via tool_use.
* **Fail-open by default**: if the classifier itself breaks, your work is not
  blocked.
* **Windows- and POSIX-friendly**: pure Python, no system services.

---

## How it fits

```
Claude Code
   |  (PreToolUse hook, forks a subprocess)
   v
hook_bridge.py   -- stdlib only, reads stdin JSON, writes stdout JSON
   |
   v  HTTP POST 127.0.0.1:8765/classify
FastAPI service (uvicorn)
   |
   +-- RulePipeline (asyncio.gather over all enabled rules)
   |     -> most-severe hit -> Decision
   +-- Claude Haiku 4.5 fallback (when no rule matches)
   |
   v
Decision JSON back to Claude Code -> approve / block / ask
```

If the service is not running, the bridge auto-starts it (best-effort, once
per host, with a filesystem lock to avoid races).

---

## Quickstart

### 1. Install (Windows / PowerShell)

```powershell
cd D:\code\ai\claude_code_classfier
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
# edit .env and put your real ANTHROPIC_API_KEY in it
```

### 1. Install (POSIX)

```bash
cd claude_code_classfier
uv venv .venv  # or python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
# edit .env
```

### 2. Start the service

```bash
# bash
bash scripts/dev.sh
# or PowerShell
powershell -File scripts/dev.ps1
```

You should see `classifier starting` and the rule count.

### 3. Smoke-test

```bash
bash scripts/smoke.sh           # POSIX
powershell -File scripts/smoke.ps1  # Windows
```

You should see `deny` for `rm -rf /tmp/test`, `git push origin main`, and
`Write` to `.env`.

### 4. Install the hook into Claude Code

```bash
bash scripts/install_hook.sh            # POSIX
powershell -File scripts/install_hook.ps1  # Windows
```

This writes (or updates) `~/.claude/settings.json` with a `PreToolUse` entry
that invokes the bridge.

### 5. Try it from Claude Code

* `echo hello` -> allowed
* `rm -rf /tmp/test` -> blocked with a clear reason
* editing `.env` -> blocked

---

## Configuration

Configuration is layered (later wins):

1. Built-in defaults
2. `config/default.yaml` (bundled)
3. `~/.config/clf/rules.yaml` (your main config)
4. Environment variables (`CLF_<SECTION>_<KEY>`, single underscore, e.g. `CLF_SERVICE_PORT=9000`)

`ANTHROPIC_API_KEY` is **always** read from the environment, never from YAML.

### Adding a custom rule

Append to `~/.config/clf/rules.yaml`:

```yaml
rules:
  - id: R-100-no-package-publish
    type: denylist_cmd
    priority: 5                # lower = more important (tie-break)
    severity: critical
    enabled: true
    pattern: "\\bnpm\\s+publish\\b"
    reason: "publishing to npm is gated for this repo"
```

Restart the service to pick up changes (`Ctrl-C` and `bash scripts/dev.sh`).

### Built-in rule types

| type            | what it does                                      |
|-----------------|---------------------------------------------------|
| `denylist_cmd`  | regex on Bash command                              |
| `sensitive_path`| glob match on file_path (Write/Edit/NotebookEdit)  |
| `branch_protect`| regex on `git push ... main/master/--force`        |

### Severity -> decision mapping

| severity | permissionDecision | decision (legacy) |
|----------|--------------------|-------------------|
| critical | `deny`             | `block`           |
| high     | `deny`             | `block`           |
| medium   | `ask`              | `block`           |
| low      | `allow`            | `approve`         |

---

## Disabling the Claude fallback

If you do not want any LLM calls, edit `~/.config/clf/rules.yaml`:

```yaml
behavior:
  enable_claude_fallback: false
  fail_open_on_error: true   # allow unmatched when fallback is off
```

Restart the service.

---

## Debugging

* `GET /health` -> liveness + rule count.
* `tail -f logs/decisions.jsonl | jq` -> full audit trail (tool / decision /
  matched_rule / took_ms / request_id).
* `CLF_LOG_LEVEL=DEBUG bash scripts/dev.sh` -> verbose logs.
* Bypass the hook temporarily: `unset` or remove the hook entry in
  `~/.claude/settings.json`.

---

## Tests

```bash
# unit (fast)
pytest tests/unit -v

# data-driven scenarios (parametrized over tests/fixtures/hook_samples.json)
pytest tests/unit/test_samples.py -v

# integration (TestClient, no uvicorn)
pytest tests/integration/test_api.py -v

# full suite incl. E2E (slow, spawns uvicorn + bridge subprocess)
pytest -v -m slow

# coverage
pytest --cov
```

---

## Layout

```
src/classifier/
  main.py                  # FastAPI entry + lifespan
  settings.py              # Pydantic Settings + YAML merging
  schemas.py               # PreToolUseEvent, Decision
  api/{classify,health}.py
  engine/
    rule.py                # Rule ABC + glob/regex helpers
    pipeline.py            # fan-out + severity pick + fail-open
    factory.py             # build_rules(specs)
    fallback.py            # Claude fallback adapter
    builtin/{denylist_cmd,sensitive_path,branch_protect}.py
  claude/
    client.py              # AsyncAnthropic + tenacity retry
    classify_tool.py       # tool_use schema
    prompt.py              # system + user templates
  bridge/hook_bridge.py    # stdin -> HTTP -> stdout, auto-starts svc
  obs/logging.py           # structlog JSONL audit

config/
  default.yaml             # bundled defaults
  rules.yaml               # committed reference rules (you can edit)

tests/
  conftest.py
  fixtures/hook_samples.json
  unit/...
  integration/...

scripts/
  dev.sh / dev.ps1
  smoke.sh / smoke.ps1
  install_hook.sh / install_hook.ps1
```

---

## Design constraints

1. `hook_bridge.py` uses **only stdlib** (urllib). Cold start < 200 ms.
2. `/classify` overall budget = hook timeout - 5 s (60 s hook -> 50 s request;
   Claude gets 8 s).
3. `Decision` carries **both** the legacy `decision` field and the new
   `hookSpecificOutput.permissionDecision` field for compatibility.
4. `fail_open_on_error` defaults to `true`; switch to fail-closed via YAML,
   not by editing code.
5. Rule `priority` convention: 1-19 deny-tier, 20-49 high-severity,
   50-99 medium, 100+ extension.