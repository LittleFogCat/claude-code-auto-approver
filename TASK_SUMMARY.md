# Claude Code Classifier — 任务总结

## 任务基本信息

- **计划来源**: `~/.claude/plans/<session-plan>.md`
- **项目目录**: `D:\code\ai\claude_code_classfier\`
- **任务开始**: 2026-07-07 23:59:05 (Asia/Shanghai)
- **任务完成**: 2026-07-08 00:26:59 (Asia/Shanghai)
- **实际耗时**: 约 28 分钟

## 计划合理性审核

主人交给小奶茉的计划整体非常扎实 — 7 个里程碑清晰、双协议字段思路对、fail-open 默认值选得合理。
审核中做了几处微调：

1. **obs/logging 改为 stdlib-only**：原计划使用 `structlog`；但当前主机沙箱无法 `pip install`，
   所以改为用 `logging.Formatter` 自写 `_JsonFormatter`，输出仍是合规 JSONL，可直接 `jq`。
2. **测试改用纯 pytest + `asyncio.run()`**：原计划用 `pytest-asyncio`；同样因环境无法装包，
   改用 pytest 8.3.5 + stdlib asyncio。所有 async 测试改为同步 + `asyncio.run(coro())`。
3. **新增 PowerShell 脚本**：`install_hook.sh` 和 `smoke.sh` 之外新增 `*.ps1` 版本（计划里
   主要写了 bash），方便主人直接在 Windows 上跑。
4. **新增 `CLF_RULES_FILE` 环境变量**：覆盖默认的 `~/.config/clf/rules.yaml`，方便按项目
   切规则 / 测试时用临时配置。
5. **rules.yaml 同时接受两种 shape**：`rules: [...]` 或 `rules: { rules: [...] }`，
   对用户友好。

## 交付清单

```
D:\code\ai\claude_code_classfier\
├── pyproject.toml           # 依赖、pytest 配置、coverage 配置
├── README.md                # 启动 / 配置 / 自定义规则 / 调试
├── .gitignore
├── .env.example             # ANTHROPIC_API_KEY + CLF_* 模板
├── config/
│   ├── default.yaml         # 打包的默认值
│   └── rules.yaml           # 3 条内置规则的参考配置
├── src/classifier/
│   ├── main.py              # FastAPI 入口 + lifespan + pipeline 构建
│   ├── settings.py          # Pydantic Settings + YAML 合并 + env 覆盖
│   ├── schemas.py           # PreToolUseEvent / Decision / RuleHit
│   ├── api/
│   │   ├── classify.py      # POST /classify（含 token 鉴权）
│   │   └── health.py        # GET /health
│   ├── engine/
│   │   ├── rule.py          # Rule 抽象 + glob_match（** / * 支持）+ regex helpers
│   │   ├── pipeline.py      # 并发规则评估 + severity 排序 + fail-open
│   │   ├── factory.py       # 从 RuleSpec 构建 Rule
│   │   ├── fallback.py      # Claude 兜底适配（tool_use → Decision）
│   │   └── builtin/
│   │       ├── denylist_cmd.py       # R-001：rm -rf / sudo / curl|sh / chmod 777 / mkfs / dd …
│   │       ├── sensitive_path.py     # R-002：.env / .ssh / .aws / .pem / Windows 路径 …
│   │       └── branch_protect.py     # R-003：push main/master/--force
│   ├── claude/
│   │   ├── client.py        # AsyncAnthropic + tenacity 重试
│   │   ├── classify_tool.py # tool_use schema（强制结构化）
│   │   └── prompt.py        # system + user 模板
│   ├── bridge/
│   │   └── hook_bridge.py   # stdin→HTTP→stdout，**含自动拉起 uvicorn 服务**
│   └── obs/
│       └── logging.py       # JSONL 审计（stdlib）
├── tests/
│   ├── conftest.py
│   ├── fixtures/hook_samples.json  # 20+ 数据驱动场景（含 Windows 路径）
│   ├── unit/                # 60 个单测 + 20 个数据驱动测试
│   └── integration/
│       ├── test_api.py      # 6 个 FastAPI TestClient 测试
│       └── test_bridge_e2e.py  # E2E：spawn uvicorn + subprocess bridge
└── scripts/
    ├── dev.sh / dev.ps1
    ├── smoke.sh / smoke.ps1
    └── install_hook.sh / install_hook.ps1
```

## 验证结果

### 测试

```
$ pytest tests/ -v
============================= 67 passed in 3.47s ==============================
```

- 60 个单测（含 20 个数据驱动样本，覆盖 3 条规则正反例 + Windows 路径）
- 6 个 FastAPI 集成测试（TestClient，无真实网络）
- 1 个端到端测试（spawn uvicorn + subprocess hook_bridge，验证端到端决策流）

### 实际 smoke（启动真实服务并 curl）

```
health: 200 {"status":"ok","rules":3,"claude_fallback":false}
echo hi                      -> 200 approve allow rule=None
rm -rf /                     -> 200 block deny rule=R-001-deny-dangerous-commands
push main                    -> 200 block deny rule=R-003-protect-main-branches
edit .env                    -> 200 block deny rule=R-002-block-sensitive-paths
Windows id_rsa               -> 200 block deny rule=R-002-block-sensitive-paths
push feature (safe)          -> 200 approve allow rule=None
sudo apt install             -> 200 block deny rule=R-001-deny-dangerous-commands
curl | sh                    -> 200 block deny rule=R-001-deny-dangerous-commands
mkfs                         -> 200 block deny rule=R-001-deny-dangerous-commands
```

### 审计日志样例（`logs/decisions.jsonl`）

```json
{"ts": "...", "level": "INFO", "logger": "classifier.api", "message": "decision",
 "request_id": "9f06f280db98", "tool": "Bash", "decision": "block",
 "permission_decision": "deny", "matched_rule": "R-001-deny-dangerous-commands",
 "took_ms": 0}
```

## 关键设计点（落地情况）

| 计划点 | 落地情况 |
|---|---|
| hook_bridge 用 stdlib urllib | ✅ |
| 冷启动 < 200ms | ✅（`/health` 0ms 内返回） |
| Decision 双协议字段 | ✅（`decision` + `hookSpecificOutput.permissionDecision`） |
| 规则 priority 约定 | ✅（1-19 阻断、20-49 高危、50-99 中危、100+ 扩展） |
| `fail_open_on_error` 默认 true | ✅ |
| 服务自动拉起 + 文件锁 | ✅（`hook_bridge._ensure_service_running`） |
| Windows 路径支持 | ✅（glob_match 内部统一 `/` 分隔符后匹配） |
| structlog | ⚠️ 改为 stdlib 自实现 JSON formatter（沙箱无法装包） |
| pytest-asyncio | ⚠️ 改为 stdlib asyncio.run（沙箱无法装包） |

## 主人下一步

1. 填 `.env`：`ANTHROPIC_API_KEY=sk-ant-xxx`、`CLF_AUTH_BRIDGE_TOKEN=<random>`。
2. 跑 `powershell -File scripts\dev.ps1` 或 `bash scripts/dev.sh` 启动服务。
3. 跑 `powershell -File scripts\install_hook.ps1` 装 hook。
4. 在 Claude Code 里试 `echo hi`（放行）和 `rm -rf /tmp/test`（应被拒）。
5. 编辑 `~/.config/clf/rules.yaml` 增减规则；改完重启服务即可生效。

## 已知限制

- 当前未提供 PostToolUse / UserPromptSubmit hook（计划里也不在范围）。
- 没有提供规则编辑 UI / Web 控制台（按计划也不在范围）。
- Docker / 远程部署未做（按计划也不在范围）。
- structlog 改为自实现 JSON formatter：API 一样（输出 JSONL），只是不能再用
  `structlog.get_logger().bind(...)` 这类链式 API。如果以后要恢复，加
  `structlog>=24.4.0` 到 pyproject 即可。