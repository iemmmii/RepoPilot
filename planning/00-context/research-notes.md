# 调研与环境记录

核对日期：2026-10-29（Asia/Shanghai）。本文件区分已经观察到的事实与仍需实验的假设。

## 本地工作区

| 项目 | 观察结果 | 能说明什么 |
| --- | --- | --- |
| 工作目录 | `D:\study agents\RepoPilot`，首次检查为空 | 无现有实现可复用；未发现本目录 `.git` |
| 项目指令 | 检查 D 盘根目录、父目录与当前目录的 `AGENTS.md`，未发现文件 | 当前没有读到额外仓库约束 |
| Git | `git --version` → `2.48.1.windows.1` | Git 命令可启动 |
| Python | `python --version` → `3.13.5`，位于 Anaconda | 解释器可启动；依赖兼容性尚未验证 |
| wsl | 能解析到 `wsl.exe` | 未检查发行版、版本或运行能力 |
| Docker | `Get-Command docker` 无结果 | 当前 PATH 中未找到命令；不能据此认定机器未安装 |
| uv / py | `Get-Command` 无结果 | 当前命令不可用；无需为本轮规划安装 |
| rg | 可解析到命令 | 可用于后续只读代码检索 |

未执行模型请求、pip 安装、镜像拉取、WSL 初始化或容器测试。真实的网络、凭据和执行环境能力需在 M1 核验。

## mini-swe-agent 核对

查询时 `main` 返回提交：`04d809ceab9df28f9adaed044884180159172930`。这是调研参照，尚未锁为项目依赖。

| 事实 | 一手来源 |
| --- | --- |
| README 明确标为 v2，旧版另有 v1 分支 | [README](https://github.com/SWE-agent/mini-swe-agent/blob/main/README.md) |
| 该提交的包内版本号为 `2.4.6` | [版本与 Protocol](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/__init__.py) |
| 项目声明 Python `>=3.10`，使用 Pydantic v2 等依赖 | [pyproject.toml](https://github.com/SWE-agent/mini-swe-agent/blob/main/pyproject.toml) |
| 可从 `run/query/execute_actions` 和环境 `execute` 附近研究适配点；`Submitted` 只是引擎退出信号 | [DefaultAgent](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py) |
| Docker 环境提供命令执行与返回码，但默认参数不等于本项目的权限策略 | [DockerEnvironment](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/environments/docker.py) |
| 许可证文件实际为 `LICENSE.md`，内容为 MIT | [LICENSE.md](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/LICENSE.md) |

README、pyproject、执行器源文件通过 GitHub 连接器读取；版本号和许可证读取了上述固定提交。开始实现前应对拟锁定版本重新完成安装与适配实验，记录依赖锁文件和接口差异。引用上游代码时保留相应声明。

## 其他设计参考

- Aider 的 Repo Map 将重要符号与相关代码组织在上下文预算内。本项目第一版借鉴检索思路，采用文件清单、文本搜索和 Python AST，不引入 Aider 运行时。[官方说明](https://aider.chat/docs/repomap.html)
- Git Worktree 支持同一仓库的多个工作树。因此它适合管理修复副本；执行权限与网络隔离仍需单独设计。[官方说明](https://git-scm.com/docs/git-worktree)
- pytest 区分测试失败、执行中断、内部/用法错误、未收集到测试等退出情况。复现不能仅依赖“返回码非零”，通过也必须核对指定测试实际执行。[官方说明](https://docs.pytest.org/en/stable/reference/exit-codes.html)

## 尚未验证的关键假设

| 假设 | 实验 | 不成立时的处理 |
| --- | --- | --- |
| v2 能在薄适配层记录命令、终止与预算 | 用受控样例执行一次完整回合 | 评估小范围派生或包装，不直接扩张到第二套完整引擎 |
| 当前机器能运行 Linux 容器 | 核验 Docker 路线和最小容器 | 保留只读调查模式，执行阶段显式环境受阻 |
| 模型接口能满足结构化输出和成本记录 | 一次最小调用与格式失败实验 | 只实现一个已验证 Provider，其他接口暂缓 |
| 文件检索加 AST 足够定位小型 Bug | 在 3 个调优案例上统计 Top-5 | 先改查询和上下文分配，再判断是否需要图或向量检索 |

没有把上游性能宣传、商业产品差异或付费需求当作已经验证的结论。作品创新性需要通过案例、对照实验和维护者反馈建立。
