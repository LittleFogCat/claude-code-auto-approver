# AGENTS.md

This file guides OpenCode (and any other agent) when working in this repository.
It is the OpenCode/agent-facing sibling of [CLAUDE.md](./CLAUDE.md) (same facts, tuned for agents).

# Codex 代码分类器

> 注意: 项目名 / 目录名带 `codex`, 但实际服务的是 **Claude Code**(见 `pyproject.toml` 描述、`main.py` 的 `app` 标题、`install_hook.py` 写 `~/.claude/settings.json`)。文档里一律写 **Claude Code**, 别被目录名带偏。

## 项目定位

本地 **PreToolUse hook 后端** 服务于 Claude Code: 拦截 Claude Code 的工具调用, 通过「正则 / 路径规则先判 → Claude Haiku 4.5 兜底」决定 approve / block / ask。

- **确定性优先**: 毫秒级规则命中直接放行/拦截。
- **Fail-open 默认**: 分类器自身出错不阻挡用户工作。
- **Windows / POSIX 友好**: 纯 Python, 无系统服务依赖。

## 顶层架构

```
Claude Code
  → hook_bridge.py   (stdlib only, stdin→stdout JSON, 自动拉起服务)
  → HTTP 127.0.0.1:8765/classify
  → FastAPI (uvicorn) [src/classifier/main.py]
       ├─ RulePipeline: asyncio.gather 跑所有 enabled 规则 → 选 severity 最高的命中
       └─ Claude Haiku 4.5 fallback: 规则无命中时用 tool_use 结构化分类
  → Decision JSON (双协议字段: legacy `decision` + new `hookSpecificOutput.permissionDecision`)
```

如果 `/health` 不通, `hook_bridge` 会用 **文件锁** (`.run/bridge.lock`) 拉起一次后台 uvicorn；冷启动 < 200ms。

## 关键约定

### 双协议 Decision 字段
`Decision` schema 同时携带 `decision` (legacy: `approve`/`block`) 与 `hookSpecificOutput.permissionDecision` (new: `allow`/`deny`/`ask`), 任意版本的 Claude Code 都能解析。**新增 endpoint 必须保持这两个字段都填**。

### Fail-open 默认
`fail_open_on_error=true` 是默认行为。任何分类器自身出错都应当 allow 用户, 不要 deny。通过 YAML/`.env` 切换 fail-closed, 不要改代码。`hook_bridge` 层还有一层 fail-open: 服务拉不起 / 请求失败时输出 `_fail_open_decision` (approve/allow) 并 exit 0。

### Severity → Permission 映射 (`engine/pipeline._hit_to_decision`)

| severity | `permissionDecision` | legacy `decision` |
|---|---|---|
| `critical` | `deny` | `block` |
| `high` | `deny` | `block` |
| `medium` | `ask` | `block` |
| `low` | `allow` | `approve` |

### Rule `priority` 约定

1-19 deny-tier / 20-49 高危 / 50-99 中危 / 100+ 扩展。命中规则比较多时, **severity 优先**, priority 数字越小越重要 (作 tie-breaker)。`pipeline._pick_best_hit` 里是 `(severity_rank, -priority)` 取 max。

### `*DEFAULT*` placeholder
YAML 规则 `pattern: "*DEFAULT*"` 表示「使用该规则内置的默认 pattern 集」(见 `engine/builtin/*_rule.py` 的 `*_PATTERNS` 常量)。这是为了用户在不写 pattern 时仍能拿到合理默认值。

### 环境变量与配置层叠
优先级 (后覆盖前): DEFAULTS → `config/default.yaml` → `~/.config/clf/rules.yaml` (或 `$CLF_RULES_FILE`) → `CLF_<SECTION>_<KEY>` 环境变量。`ANTHROPIC_API_KEY` 永远从环境变量读, 不进 YAML。注意: `config/rules.yaml` **不是** 自动加载的默认值 (只作参考模板), 真正打包的默认在 `config/default.yaml`; 用户配置在 `~/.config/clf/rules.yaml` 会**整体替换**默认规则。

## 目录速查

```
src/classifier/
  main.py                  # FastAPI 入口 + lifespan + 构造 RulePipeline
  settings.py              # Pydantic Settings + YAML 合并 + 环境变量
  schemas.py               # PreToolUseEvent, Decision, RuleHit, PipelineContext
  api/
    classify.py            # POST /classify + token 鉴权 + audit log
    health.py              # GET /health
  engine/
    rule.py                # Rule ABC + glob_match (** / * 支持) + regex 辅助
    pipeline.py            # 并发规则评估 + severity 挑最严的 + fail-open
    factory.py             # build_rules(specs) — type 字符串 → Rule 类
    fallback.py            # ClaudeFallback (tool_use → Decision)
    builtin/               # 三个内置规则: denylist_cmd / sensitive_path / branch_protect
  claude/
    client.py              # AsyncAnthropic + tenacity 重试
    classify_tool.py       # 给 LLM 的 tool_use schema (强制结构化输出)
    prompt.py              # system + user 模板
  bridge/
    hook_bridge.py         # stdlib-only, stdin→HTTP→stdout, 自动拉起 uvicorn
    quiet_runner.py        # 先 NUL 掉 stderr/stdout 再 import bridge (防 Win32 弹窗)
  obs/logging.py           # stdlib JSONL formatter (无 structlog 依赖)

config/
  default.yaml             # 打包的默认值 (真正生效的默认)
  rules.yaml               # 参考规则模板 (不自动加载, 用户可拷到 ~/.config/clf/)

scripts/
  dev.sh / dev.ps1         # 前台跑 uvicorn (--reload)
  smoke.sh / smoke.ps1     # 烟测: 断言 deny 几条危险命令
  install_hook.py          # 写 ~/.claude/settings.json (见下方跨平台钩子注意)
  disable_hook.py          # 卸载钩子
  observer_cli.py          # 终端实时 tail logs/decisions.jsonl
  observer_gui.py(.bat/.vbs) # Tk 弹窗实时监控

tests/
  conftest.py              # pipeline / rules / settings 共享 fixture
  fixtures/hook_samples.json  # 20 个数据驱动场景 (含 Windows 路径)
  unit/                    # 单测 (含 test_samples.py 数据驱动)
  integration/             # FastAPI TestClient + E2E (spawn uvicorn + bridge)
```

`.run/` 是运行时目录 (`bridge.lock`、后台 uvicorn 日志), 已 gitignore, 勿提交。

## 常用命令

> 所有命令假定 cwd 是**仓库根目录**（即包含 `.venv/`、`scripts/`、`tests/` 的目录）。使用项目自带的 `.venv`。

```bash
# 安装依赖 (含 dev 工具)
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows
.venv/bin/python -m pip install -e ".[dev]"          # POSIX

# 启动服务
bash scripts/dev.sh                # POSIX
powershell -File scripts/dev.ps1    # Windows

# 烟测 (启动后另起终端)
bash scripts/smoke.sh
powershell -File scripts/smoke.ps1

# 装 hook 到 ~/.claude/settings.json (Windows: 用 .py, 勿用不存在的 .ps1)
.venv/Scripts/python scripts/install_hook.py
.venv/bin/python scripts/install_hook.py
# 卸载: python scripts/disable_hook.py

# Lint
.venv/bin/python -m ruff check src tests

# 单测 (快速)
.venv/bin/python -m pytest tests/unit -v
# 数据驱动场景 (20 个样本, 走 tests/fixtures/hook_samples.json)
.venv/bin/python -m pytest tests/unit/test_samples.py -v
# 集成 (FastAPI TestClient, 不开 uvicorn)
.venv/bin/python -m pytest tests/integration/test_api.py -v
# 完整 E2E (慢: spawn uvicorn + subprocess 跑 bridge)
.venv/bin/python -m pytest -v -m slow
# 全套 + 覆盖率
.venv/bin/python -m pytest --cov

# 调试 / 配置 override
python -c "from classifier.settings import Settings; print(Settings.load().model_dump_json(indent=2))"
```

注意: **`install_hook.sh` / `install_hook.ps1` 并不存在**, 只有 `install_hook.py` (跨平台)。

新增/修改规则后必须 **重启服务** (`Ctrl-C` 然后再跑 `scripts/dev.*`); 规则是启动时一次加载。

## 新增自定义规则

往 `~/.config/clf/rules.yaml` 追加一条 (id 全局唯一, 不要与 R-001~R-003 冲突):

```yaml
rules:
  - id: R-100-no-npm-publish
    type: denylist_cmd          # 可选: denylist_cmd | sensitive_path | branch_protect
    priority: 5                 # 数字越小越优先, 用于同 severity 时 tie-break
    severity: critical          # critical/high → deny | medium → ask | low → allow
    enabled: true
    pattern: "\\bnpm\\s+publish\\b"   # 对 denylist_cmd/branch_protect 是 regex
    # paths: ["**/.envrc"]              # 对 sensitive_path 用 paths (glob 支持)
    reason: "publishing to npm is gated for this repo"
```

要新增一种**规则类型**, 在 `engine/builtin/<name>.py` 写一个 `Rule` 子类 + `from_spec`, 再去 `engine/factory._REGISTRY` 注册。

## Windows 钩子 / 跨平台坑 (别手滑改坏)

- 钩子命令 = `.venv` 里的 `python -m classifier.bridge.quiet_runner` (`install_hook.py:_hook_command`)。
- **不要** 在钩子链上引入 `wscript.exe` / `run_hidden.vbs` / `pythonw.exe`: `.venv` 脚本是 uv trampoline, `pythonw.exe` trampoline 是 GUI 子系统, 会无控制台地拉起 BASE python.exe, 于是 Win11 默认终端会**每个工具调用弹一个 Windows Terminal 窗口**。`quiet_runner.py` 存在的唯一意义就是先 NUL 掉 stderr/stdout 再 import bridge, 防 `cmd` 弹窗。
- `hook_bridge._spawn_service` 用 `CREATE_NO_WINDOW` + 控制台 `python.exe` 后台拉 uvicorn; 不要改成 `pythonw` 或加 `DETACHED_PROCESS`。

## 调试清单

- `GET http://127.0.0.1:8765/health` → liveness + 启用规则数。
- `tail -f logs/decisions.jsonl | jq` → 全量审计 (tool / decision / matched_rule / took_ms / request_id)。或 `python scripts/observer_cli.py` 实时看。
- `CLF_LOG_LEVEL=DEBUG bash scripts/dev.sh` → 详细日志 (包含 Claude fallback 调试)。
- 临时绕过 hook: 直接编辑 `~/.claude/settings.json` 删掉 `PreToolUse` 那一项, 或用环境变量 `CLF_BRIDGE_TOKEN` 强制鉴权失败 (会触发 401 → fail-open)。
- 桥接层调不到服务时, 看 `.run/bridge.lock` (锁过期 30s) 与 `logs/service.log` (后台 uvicorn 输出)。

## 范围之外 (not implemented)

- `PostToolUse` / `UserPromptSubmit` hook — 仅 PreToolUse。
- 规则编辑 UI / Web 控制台 — 仅手编 YAML。
- Docker / 远程部署 — 纯本地进程 (uvicorn + subprocess)。

## 路径分隔符约定

代码里和 YAML `paths:` 里都用 `/`, Windows 用户也照写 (`C:/Users/foo`). `engine/rule._normalize_separators` 会在 glob 匹配前把 `\` 替换为 `/`, 所以反斜杠也能用但是**不要混用**。文档/注释里一律写 `/`。

## Git提交规范

1. Git提交信息需符合 `conventional commit` 规范。
2. Git提交信息使用中文。
3. 当用户要求提交代码时，直接执行提交+推送的操作，无需用户再次确认。
