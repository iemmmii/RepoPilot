# M3 受管候选与补丁交付记录

日期：2026-10-30。关联 P3-01；设计与实施依据见[本单元规划](../03-plan/m3-candidate-management.md)，D-023 记录最终取舍。

## 实际交付

- `domain/patches.py`：严格 JSON 提案、版本清单与导出契约；单批最多 8 个文件、256KB 内容，单文件 64KB。
- `repository/candidates.py`：候选创建、应用、状态、导出、导出适用性与 release；独立 worktree/原始 blob/临时 index，不 checkout 或执行目标代码。
- 每个候选保留初始 base 与最多十次尝试；新版本以原子 candidate.json 发布，提交前崩溃形成 orphan，不复用其数据、不退还目录预算。累计导出补丁最多 1MB。
- 禁止已有测试、配置、路径穿越、Windows 保留路径、大小写目录碰撞、链接/junction、陈旧原文与语法错误。批次拒绝不修改已发布版本；中间版本审计损坏也拒绝后续写入。
- 导出 JSON 与 Diff 绑定固定版本；check-export 返回 current/superseded/retired/unverifiable。候选生成和导出始终 unverified，不自动获得测试成功。
- release 先发布退休状态，核对候选内容、链接、绝对路径和 Git worktree 注册后，仅移除匹配目录；保留审计文件与锁，不全局 prune。中断可继续退休流程，未知 orphan 和被改动的目录留待人工处理。
- 现有源码物化器提取可复用的只读 raw-blob 接口，并提前拒绝目录级大小写碰撞；未改变原有验证语义。

## 正式受控对照

评估目录：`.repopilot/evaluations/m3-candidate-3c6afc61498044f6b2d6ec4e5b9b2a59`。这是手写 C01 补丁，不是模型生成或真实 Issue 修复率；模型请求为 0。

| 尝试 | 候选 | Run ID | 真实结果 |
| --- | --- | --- | --- |
| 错误修改 500 → 403 | c04474620ed5929bfc5e211bed5a4e77969cc195 | b3cfc66af33e4f0eaaf1afd71e245e84 | base 目标失败/回归通过；candidate 目标仍失败；outcome=reproduced，未获得修复成功 |
| 正确修改 403 → 401 | 60ea7441bb3ab3e2a52680a9bdd97fe6421ec017 | 4393c0ae790d4eaebeed71291f248756 | 相同冻结套件，base 目标失败/回归通过，candidate 全部通过；candidate_verified |

两次 Run 各执行 2 条命令，Artifact/graph 完整性均 valid。第二次修改之后，第一次导出为 superseded，当前导出为 current；历史 Run 和 Diff 未改写。原始 summary、验证检查与命令证据留在忽略目录。

## 验证与发现

本地默认全套 **144 passed / 14 skipped**：13 个真实容器测试默认跳过，另 1 个 junction 受当前沙箱策略限制。真实 Docker 全套单列 **13 passed**；Windows junction、退休、进程中断及路径反例的本机定向执行 **4 passed**。随后新增的“Git 已移除但退休检查点尚未写入”回归定向 **1 passed**，验证后续继续清理可完成，未为此重复全部不相关测试。远程 CI 结果在实际完成后追加。

ruff check / format 通过（59 个 Python 文件），uv.lock 离线检查通过，隔离 wheel/sdist 构建成功。分发包分别 44/64 个条目，包含新模块且没有 .env、.venv、.repopilot 或安装器；26 个 Markdown 文件的 94 个相对链接通过。

- 首轮测试发现 Windows 工作区的 CRLF 与 Git 对象 LF 不同。候选本来读取 raw blob，修正测试的比较基准为固定 Git 对象，未将工作区换行或用户改动混入候选。
- 正式脚本最初错误期待失败候选返回 needs_human，因而脚本断言退出 1；实际 Gate 按既有契约返回 reproduced，并明确候选断言未全部通过。核对 Gate 后单独校验原始结果，全部六项协议检查通过；未重跑或改写 Run 来满足错误预期。
- 非隔离 build 命令最初因本地 venv 没有 setuptools 失败。项目已经声明构建依赖，改用 uv 的离线隔离构建，不为构建工具增加运行时依赖。
- 默认沙箱阻止测试创建 Windows junction，因此该项明确 skip；同一测试在授权的普通本机进程中实际通过，未关闭任何全局保护。Linux CI 另覆盖 symlink。

## 版本与边界

规划提交 32a4acf 已先推送。交付分支 `codex/m3-candidate-management`，[PR #8](https://github.com/iemmmii/RepoPilot/pull/8) 当前以 PR #7 分支为基础，未自动合并；#7 已在本轮成功转为可审阅状态。

本单元完成候选管理的窄权限版本。P3-02 的生产 Coding Engine、真实模型生成修复、完整动态失效、所有故障与机制对照仍未完成。`status <run>` 仍是历史完整性检查；check-export 不声称检查 Oracle、环境或评估策略变化。结果最多 candidate_verified，不产生 resolved_verified。

下一步接 mini-swe-agent 2.4.6 的 Model/Environment 接口、持久模型预算与有限修复尝试，再完成至少两个模型修复和诚实失败案例。
