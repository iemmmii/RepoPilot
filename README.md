# RepoPilot

面向 GitHub Issue 的证据驱动调查、复现、修复与验收 Agent，重点研究修复结论的可追溯性、证据失效与可靠恢复。

M1 已实现 **Issue → 固定 Git 版本 → 相关代码定位 → 带文件依据的调查报告**，支持 DeepSeek 和离线检索模式。当前不执行目标项目代码或测试。

项目不设固定完成期限，按质量里程碑推进。后续研究证据失效、独立 Oracle、隔离复现、修复与可靠恢复；这些后续能力尚未实现。

## 运行

使用 Python 3.11+ 和 uv，按锁文件安装：

```powershell
uv sync --locked
uv run repopilot doctor
```

DeepSeek 从本地 `.env` 读取 `DEEPSEEK_API_KEY`；配置格式见 `.env.example`。已有 `.env` 时保留原配置，密钥不要提交到 Git。

```powershell
uv run repopilot investigate --issue-url https://github.com/pallets/itsdangerous/issues/126 --repo <本地仓库路径> --ref 6e6359864be6055860adf1e11d8bb0db69ff1840
```

离线使用 `--issue-file examples/issues/itsdangerous-126.json --provider lexical`。报告与 manifest 保存在 `.repopilot/runs/<run_id>/`；`repopilot status <run目录>` 核对产物完整性，不代表修复已完成。完整样例准备、本机运行和验证记录见 [M1 交付记录](planning/04-progress/m1-investigation.md)。

## 代码布局

```text
src/repopilot/
├── cli.py、__main__.py    # 命令行入口
├── domain/               # 领域记录、契约、错误
├── github/               # Issue 输入与只读 API
├── repository/           # Git 快照、静态检索与 AST
├── providers/            # Provider 协议、DeepSeek、离线基线
├── workflow/             # 调查编排
├── storage/              # 产物、检查点与完整性
├── reporting/            # 报告渲染
└── diagnostics/          # 环境诊断
```

测试按 `tests/unit/<功能>/` 与 `tests/integration/` 分开。未来模块在需要时加入，不提前创建空子系统。

## 验证

```powershell
uv run --frozen ruff check src tests scripts
uv run --frozen ruff format --check src tests scripts
uv run --frozen pytest -q
```

单元与集成测试禁用 Python 网络连接，模型 HTTP 使用 MockTransport。真实模型验证是单独的手动样例，不在 CI 中读取 API 密钥。

- [规划总入口](planning/README.md)
- [实施里程碑](planning/03-plan/milestones.md)
- [当前进度](planning/04-progress/progress.md)
- [版本控制规范](planning/05-decisions/version-control.md)

规划、设计和进度统一存放在 `planning/`，与程序源码、测试及个人运行数据分开。
