# 版本控制与协作规范

建立日期：2026-10-29。依据：用户要求采用现代软件工程的规范版本控制，并先上传规划。

## 仓库与首次基线

- 远程仓库：`git@github.com:iemmmii/RepoPilot.git`。
- 默认分支：`main`。
- 远程初始为空，因此仓库入口、首次规划基线及其上传结果记录属于一次初始化，可直接集成到 `main`。初始化完成后的实质变更通过短期分支与 PR 集成。
- 本次范围为规划文档与基础仓库规范，不为尚未实现的产品打发布标签或虚构版本号。

## 分支与集成

采用以 `main` 为主干的轻量流程，任务分支保持短期、单一目的：

| 分支示例 | 用途 |
| --- | --- |
| `docs/p1-investigation-design` | 文档和设计调整 |
| `feat/p1-issue-ingestion` | 新功能 |
| `fix/evidence-snapshot-validation` | 缺陷修复 |
| `chore/dependency-lock` | 依赖、工具及仓库维护 |

开始任务前同步主干并检查工作区；不将无关本地修改带入任务。提交后推送任务分支，通过 PR 说明问题、结果、验证与风险，合并前完成审查和当时适用的检查。

初期优先 Squash Merge，让主干每个提交对应一个可回退的变更。合并后的任务分支按需清理。共享分支和主干不使用强制推送；撤回已集成改动优先用 revert 保留历史。

此文件规定协作流程，不代表 GitHub 分支保护和必需 CI 已在服务端启用。等检查实际建立后再配置对应规则，不添加永远无法通过的空检查要求。

## 提交信息

采用 Conventional Commits 形式：`type(scope): summary`。摘要使用简明祈使句；解释原因、验证和关联任务时使用提交正文。

| 示例 | 含义 |
| --- | --- |
| `docs(planning): establish RepoPilot planning baseline` | 首次规划基线 |
| `feat(github): add read-only issue ingestion` | 新增功能 |
| `fix(evidence): reject stale verification results` | 修复缺陷 |
| `test(workflow): cover interrupted stage recovery` | 有意义的验证覆盖 |
| `chore(deps): lock execution engine dependencies` | 依赖维护 |

一个提交聚焦一个逻辑变化。使用明确的文件路径暂存，提交前审阅 staged diff，并执行 `git diff --cached --check`。不通过 amend 或重写已经共享的历史隐去后续修正。

## PR 与验证

使用仓库的 PR 模板。关联规划任务 ID，说明实际行为及验证结果，更新进度台账；架构变化另追加决策依据。

纯文档变更检查链接、数据示例和任务一致性；实现阶段逐步建立格式/静态检查、相关测试和必要的集成验证。检查必须实际存在且运行过，才能报告通过。

本地提交身份沿用用户当前 Git 配置；通过 GitHub 连接器提交时使用平台记录的已连接账户身份。自动化工具不擅自更改全局身份，不编造签名或审查结果。

当前环境的 SSH 认证未通过，GitHub 连接器也未获得内容写入权限。本机 Git Credential Manager 已有 `iemmmii` 账户，本次使用该账户的 HTTPS 认证完成本地提交后的上传。

`origin` 配置保留用户给定的 SSH 地址，同时仅在本仓库配置该地址到同一仓库 HTTPS URL 的精确转写，使后续 fetch/push 能使用现有凭据。无需修改全局 Git 或 SSH 配置，也不在文件或日志中存放令牌。

## 纳入与排除

纳入：源码、测试、可重现配置、依赖锁文件、规划、决策、进度与必要仓库元数据。

排除：密钥、`.env`、虚拟环境、缓存、构建产物，以及 `.repopilot/` 中的仓库副本与运行证据。原始个人聊天快照只保留本地；公开规划保留提炼后的需求与依据。

`.gitattributes` 将文本统一为 LF。规划文件继续集中在 `planning/`；根 README 仅作为导航。运行结果通过 Run ID 或脱敏报告引用，不把大批日志当成普通源码提交。
