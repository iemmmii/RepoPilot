# RepoPilot

面向 GitHub Issue 的证据驱动调查、复现、修复与验收 Agent，重点研究修复结论的可追溯性、证据失效与可靠恢复。

已实现 **Issue → 固定 Git 版本 → 带文件依据的调查报告**，支持 DeepSeek 和离线检索。M2 新增显式复现和已知候选对照：冻结外部 unittest，在受限 Linux 容器执行并保存命令证据、Oracle、输入摘要和证据 DAG。

项目不设固定完成期限，按质量里程碑推进。当前支持受管候选提案、指定 Git ref 验证及验证阶段恢复；尚未接入模型修复或执行完整项目回归。结果最多为 candidate_verified，不宣称 Issue 已完整解决。

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

## 复现与候选对照

需要本机 Linux Docker 引擎；Windows 已验证 WSL2 + Docker Desktop。产品不会自动拉取镜像、安装目标依赖或回退宿主执行。首次使用显式准备固定镜像与样例仓库，已有仓库目录时保留原目录：

```powershell
docker pull python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
git clone --no-checkout https://github.com/pallets/itsdangerous.git .repopilot/repositories/itsdangerous
uv run repopilot verify-candidate --issue-file examples/issues/itsdangerous-126.json --repo .repopilot/repositories/itsdangerous --base-ref 1a9b8d1f9968eb248bda69f39d373a6330b692ba --candidate-ref c30678d19e37011890e2374cca04f7789e101793 --suite examples/verification/itsdangerous-126/suite --oracle examples/verification/itsdangerous-126/oracle.json
```

仅复现时改用 `reproduce` 并省略 `--candidate-ref`。`investigate` 仍始终只读，不会自动运行报告中的候选命令。模型密钥不会传给容器，这两个验证命令不调用模型。

`--suite` 和 `--oracle` 是操作者审核过的控制面输入，不能直接采用 Worker 提供的 accepted 声明；套件字节必须匹配 Oracle 的 suite_hash，所有指定目标和回归 ID 必须实际执行。示例的独立依据来自已合并的上游 PR #133，而非本次测试结果。具体范围、真实结果及限制见 [M2 交付记录](planning/04-progress/m2-controlled-verification.md)。

## 阶段恢复与受控评估

新验证 Run 使用 0.3 manifest。`resume` 先重新核对冻结输入、当前 Git ref、Oracle、镜像和执行器版本；只有完整提交的阶段才复用，未提交尝试在新容器重跑。命令与保守时间预算不会因恢复归零。旧 0.1/0.2 Run 可查询，不能直接升级恢复。

```powershell
uv run repopilot resume <run目录>
uv run repopilot evaluate
```

`evaluate` 运行三个版本化受控调优案例，保存到 `.repopilot/evaluations/`：错误状态码、空输入及依赖缺失。它使用已知候选，不调用模型；这些结果不代表真实 Agent 修复率。完整边界、进程退出实验和评估记录见 [M2 恢复与评估记录](planning/04-progress/m2-stage-recovery.md)。

## 受管候选补丁

从固定 base 创建独立候选，使用 JSON 提案替换已有 Python 实现文件。每项修改包含 `path`、当前原文的 `before_sha256` 和完整新 `content`，顶层包含 `explanation` 与 `replacements`。协议定义见 `src/repopilot/domain/patches.py`。

```powershell
uv run repopilot candidate create --repo <本地仓库> --base-ref <固定提交>
uv run repopilot candidate apply <candidate_dir> --proposal <proposal.json>
uv run repopilot candidate export <candidate_dir> --output-dir <新的导出目录>
uv run repopilot candidate check-export <candidate_dir> --export-dir <导出目录>
uv run repopilot candidate status <candidate_dir>
```

导出目录包含 `patch.diff` 和 `candidate.json`；后者的 `base_ref`/`candidate_ref` 可用于前述 `verify-candidate`。导出本身是 unverified，不执行测试。候选更新后，旧导出查询返回 superseded 和退出码 1；历史验证仍只适用于当时的固定提交。`status <run目录>` 目前仍仅检查历史 Run 完整性，不自动检查候选、Oracle 或环境是否变化。

候选不改动用户原工作区或 index，不运行目标 hooks/过滤器。首版拒绝新增/删除文件、测试、配置、链接及未匹配原文摘要的修改；最多十次修改尝试，中断产生的 orphan 同样占用目录上限。未提交的版本不会自动晋升。

需要回收已导出候选时运行 `uv run repopilot candidate release <candidate_dir>`：退休会话并移除其已核验的受管工作树，保留提案、补丁和 manifest；遇到修改或链接时拒绝删除，orphan 需人工检查，不运行全局 prune。释放后禁止继续修改和导出，Git 对象未来可能被仓库 GC 清理。实际验收见 [M3 候选记录](planning/04-progress/m3-candidate-management.md)。

## 代码布局

```text
src/repopilot/
├── cli.py、__main__.py    # 命令行入口
├── domain/               # 领域记录、契约、错误
├── github/               # Issue 输入与只读 API
├── repository/           # Git 快照、静态检索、候选与补丁
├── providers/            # Provider 协议、DeepSeek、离线基线
├── sandbox/              # 受限 Docker 生命周期、预算与命令证据
├── verification/         # 冻结测试观察与确定性 Gate
├── workflow/             # 调查、复现与候选对照编排
├── evaluation/           # 版本化受控调优案例与结果清单
├── storage/              # 产物、检查点与完整性
├── reporting/            # 报告渲染
└── diagnostics/          # 环境诊断
```

测试按 `tests/unit/<功能>/`、`tests/integration/` 与 `tests/container/` 分开。未来模块在需要时加入，不提前创建空子系统。

## 验证

```powershell
uv run --frozen ruff check src tests scripts
uv run --frozen ruff format --check src tests scripts
uv run --frozen pytest -q
```

单元与集成测试禁用 Python 网络连接，模型 HTTP 使用 MockTransport。真实模型验证是单独的手动样例，不在 CI 中读取 API 密钥。

真实容器测试需要已缓存的镜像；Windows 使用 `$env:REPOPILOT_DOCKER_TESTS='1'` 后运行 `uv run --frozen pytest -q tests/container`。CI 另设 Linux 容器作业，显式拉取固定公开镜像后执行，不把默认跳过记作容器测试通过。

- [规划总入口](planning/README.md)
- [实施里程碑](planning/03-plan/milestones.md)
- [当前进度](planning/04-progress/progress.md)
- [版本控制规范](planning/05-decisions/version-control.md)

规划、设计和进度统一存放在 `planning/`，与程序源码、测试及个人运行数据分开。
