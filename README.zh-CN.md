# Claude Code 分类器

[English](./README.md) | 简体中文

一个面向 Claude Code 的本地 **PreToolUse hook 后端**。它夹在 Claude Code
和操作系统之间，决定每一次工具调用是否应该执行，并自动拦截危险操作。

* **确定性优先**：正则 / 路径规则在毫秒级完成匹配。
* **Claude Haiku 4.5 兜底**：规则没有命中时，由 Claude 通过 `tool_use`
  对工具调用进行结构化分类。
* **Fail-open 默认**：分类器自身出错时不会阻挡你的工作。
* **Windows / POSIX 友好**：纯 Python，不依赖任何系统服务。

---

## 工作原理

```
Claude Code
   |  (PreToolUse hook，fork 一个子进程)
   v
hook_bridge.py   -- 仅用标准库，读取 stdin JSON，写出 stdout JSON
   |
   v  HTTP POST 127.0.0.1:8765/classify
FastAPI 服务 (uvicorn)
   |
   +-- RulePipeline (asyncio.gather 并发跑所有启用的规则)
   |     -> 取 severity 最高的命中 -> Decision
   +-- Claude Haiku 4.5 兜底 (规则无命中时)
   |
   v
Decision JSON 回传 Claude Code -> approve / block / ask
```

如果服务没有运行，桥接层会自动拉起它（尽力而为，每台主机一次，用文件锁
避免并发竞争）。冷启动 < 200ms。

---

## 快速开始

### 1. 安装 (Windows / PowerShell)

```powershell
cd D:\code\ai\claude_code_classfier
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
# 编辑 .env，填入真实的 ANTHROPIC_API_KEY
```

### 1. 安装 (POSIX)

```bash
cd claude_code_classfier
uv venv .venv  # 或 python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
# 编辑 .env
```

### 2. 启动服务

```bash
# bash
bash scripts/dev.sh
# 或 PowerShell
powershell -File scripts/dev.ps1
```

你应该能看到 `classifier starting` 以及加载的规则数量。

### 3. 烟测

```bash
bash scripts/smoke.sh              # POSIX
powershell -File scripts/smoke.ps1 # Windows
```

你应该能看到对 `rm -rf /tmp/test`、`git push origin main` 以及向 `.env`
写入的操作返回 `deny`。

### 4. 把 hook 安装进 Claude Code

```bash
bash scripts/install_hook.sh              # POSIX
powershell -File scripts/install_hook.ps1 # Windows
```

这会向 `~/.claude/settings.json` 写入（或更新）一个 `PreToolUse` 条目，
指向桥接层。

### 5. 在 Claude Code 里试用

* `echo hello` -> 放行
* `rm -rf /tmp/test` -> 拦截，并给出明确原因
* 编辑 `.env` -> 拦截

---

## 配置

配置采用层叠覆盖（后者覆盖前者）：

1. 内置默认值
2. `config/default.yaml`（随包发布）
3. `~/.config/clf/rules.yaml`（你的主要配置）
4. 环境变量（`CLF_<SECTION>_<KEY>`，单下划线，例如
   `CLF_SERVICE_PORT=9000`）

`ANTHROPIC_API_KEY` **永远**从环境变量读取，不进 YAML。

### 新增自定义规则

往 `~/.config/clf/rules.yaml` 追加一条：

```yaml
rules:
  - id: R-100-no-package-publish
    type: denylist_cmd
    priority: 5                # 数字越小越优先（同 severity 时的 tie-break）
    severity: critical
    enabled: true
    pattern: "\\bnpm\\s+publish\\b"
    reason: "publishing to npm is gated for this repo"
```

修改后需要**重启服务**才能生效（`Ctrl-C` 然后再跑 `bash scripts/dev.sh`）。

### 内置规则类型

| 类型             | 作用                                               |
|------------------|----------------------------------------------------|
| `denylist_cmd`   | 对 Bash 命令做正则匹配                             |
| `sensitive_path` | 对 file_path 做 glob 匹配 (Write/Edit/NotebookEdit) |
| `branch_protect` | 对 `git push ... main/master/--force` 做正则匹配   |

### severity -> 决策映射

| severity | permissionDecision | decision (legacy) |
|----------|--------------------|-------------------|
| critical | `deny`             | `block`           |
| high     | `deny`             | `block`           |
| medium   | `ask`              | `block`           |
| low      | `allow`            | `approve`         |

> `Decision` 同时携带 legacy 的 `decision` 字段与新的
> `hookSpecificOutput.permissionDecision` 字段，任意版本的 Claude Code 都能
> 解析。新增 endpoint 时必须同时填写这两个字段。

### `*DEFAULT*` 占位符

YAML 规则里写 `pattern: "*DEFAULT*"` 表示「使用该规则内置的默认 pattern
集合」（见 `engine/builtin/*_rule.py` 里的 `*_PATTERNS` 常量）。这样用户
不写 pattern 也能拿到合理的默认值。

---

## 关闭 Claude 兜底

如果你不希望发起任何 LLM 调用，编辑 `~/.config/clf/rules.yaml`：

```yaml
behavior:
  enable_claude_fallback: false
  fail_open_on_error: true   # 兜底关闭时，无命中的请求放行
```

然后重启服务。

---

## 调试

* `GET /health` -> 存活检查 + 已启用规则数。
* `tail -f logs/decisions.jsonl | jq` -> 全量审计（tool / decision /
  matched_rule / took_ms / request_id）。
* `CLF_LOG_LEVEL=DEBUG bash scripts/dev.sh` -> 详细日志。
* 临时绕过 hook：删掉 `~/.claude/settings.json` 里的 `PreToolUse` 条目，
  或用环境变量 `CLF_BRIDGE_TOKEN` 让鉴权失败（会触发 401 -> fail-open）。
* 桥接层调不到服务时，查看 `.run/bridge.lock`（锁 30s 过期）与
  `logs/service.log`（后台 uvicorn 输出）。

---

## 测试

```bash
# 单测（快）
pytest tests/unit -v

# 数据驱动场景（基于 tests/fixtures/hook_samples.json 参数化）
pytest tests/unit/test_samples.py -v

# 集成测试（TestClient，不开 uvicorn）
pytest tests/integration/test_api.py -v

# 完整 E2E（慢：spawn uvicorn + bridge 子进程）
pytest -v -m slow

# 全套 + 覆盖率
pytest --cov
```

---

## 目录结构

```
src/classifier/
  main.py                  # FastAPI 入口 + lifespan
  settings.py              # Pydantic Settings + YAML 合并
  schemas.py               # PreToolUseEvent, Decision
  api/{classify,health}.py
  engine/
    rule.py                # Rule ABC + glob/regex 辅助
    pipeline.py            # 并发评估 + severity 取最严 + fail-open
    factory.py             # build_rules(specs)
    fallback.py            # Claude 兜底适配器
    builtin/{denylist_cmd,sensitive_path,branch_protect}.py
  claude/
    client.py              # AsyncAnthropic + tenacity 重试
    classify_tool.py       # tool_use schema
    prompt.py              # system + user 模板
  bridge/hook_bridge.py    # stdin -> HTTP -> stdout，自动拉起服务
  obs/logging.py           # stdlib JSONL 审计

config/
  default.yaml             # 随包默认值
  rules.yaml               # 提交到仓库的参考规则（可自行修改）

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

## 设计约束

1. `hook_bridge.py` **只用标准库**（urllib）。冷启动 < 200ms。
2. `/classify` 整体预算 = hook 超时 - 5s（60s hook -> 50s 请求；Claude 拿 8s）。
3. `Decision` **同时**携带 legacy 的 `decision` 字段与新的
   `hookSpecificOutput.permissionDecision` 字段，保证兼容性。
4. `fail_open_on_error` 默认为 `true`；要切换为 fail-closed，改 YAML，不要改
   代码。
5. 规则 `priority` 约定：1-19 deny 档 / 20-49 高危 / 50-99 中危 / 100+ 扩展。
   命中规则较多时，**severity 优先**，priority 数字越小越重要（作 tie-break）。

---

## 范围之外（暂未实现）

* `PostToolUse` / `UserPromptSubmit` hook —— 仅支持 PreToolUse。
* 规则编辑 UI / Web 控制台 —— 仅手编 YAML。
* Docker / 远程部署 —— 纯本地进程（uvicorn + subprocess）。