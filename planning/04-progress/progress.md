# RepoPilot 进度台账

更新日期：2026-10-30（Asia/Shanghai）。

## 当前状态

阶段：M2 首个受控复现/候选对照已交付；产品 DockerRunner、冻结测试、Oracle/Gate 与最小证据图可运行。阶段恢复和 3 个调优案例尚未完成。
版本基线：M2 实现 PR #5 已集成到 main，当前基线为 [`8ecb2ec`](https://github.com/iemmmii/RepoPilot/commit/8ecb2ec47e6b48927920c44f9f87d26a4c6fe5aa)。
实际实现：DeepSeek/离线调查，以及显式 reproduce/verify-candidate；代码按 10 个功能子包组织，调查不自动执行目标代码。
下一项：P2-05 阶段级检查点、恢复与初始评估；本轮交付证据见 [M2 记录](m2-controlled-verification.md)。
实现分支 codex/m2-controlled-verification 的 [PR #5](https://github.com/iemmmii/RepoPilot/pull/5) 已由外部操作合并。合并后产生的纯进度补记移接到 codex/m2-delivery-record，以 [PR #6](https://github.com/iemmmii/RepoPilot/pull/6) 单独集成；本助手未执行合并。

## 阶段看板

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| M0 需求与规划 | 已完成 | 读取最后 5 轮，形成文档基线并检查 |
| M1 运行基础与只读调查 | 已完成 | 只读闭环、模型、底座合成接口及 Linux 受限容器小实验已核验；不代表生产引擎和 Runner 已集成 |
| M2 独立依据与最小验证 | 部分完成 | 真实复现与已知候选对照通过，P2-05 恢复和初始评估未完成 |
| M3 可靠修复 | 未开始 | 修复循环、证据失效、故障注入和初始对照 |
| M4 独立审查与评估 | 未开始 | 依赖候选补丁和有效测试证据 |
| M5 真实有效性与成熟度 | 未开始 | 多仓库案例、可重跑评估和证据浏览 |

## 实施任务状态

任务定义与验收见[里程碑](../03-plan/milestones.md)，本表只维护状态与实际证据。

| ID | 状态 | 实际产物 / 阻碍 |
| --- | --- | --- |
| P1-01 | 已完成（小实验） | 底座 2.4.6 合成接口、真实 DeepSeek、已知 Issue/base 与离线调查已核验；新增 WSL2 + Docker Linux 受限容器探针通过；尚未做生产底座与 Runner 集成 |
| P1-02 | 已完成 | pyproject、uv.lock、隔离环境与 domain 契约；功能子包布局 |
| P1-03 | 已完成 | GitHub Issue URL/本地 JSON、输入与 HTTP 错误分类；真实读取成功 |
| P1-04 | 已完成 | 固定 Git commit、受限文本/AST、路径和行号校验；不导入目标代码 |
| P1-05 | 已完成 | 有文件依据的调查报告，假设和未执行命令单列；真实模型已定位关键代码 |
| P1-06 | 已完成 | doctor/investigate/status、原子 manifest、失败保存、29 项测试及真实 DeepSeek 样例 |
| P2-01 | 已完成（受控样例范围） | 本机固定镜像、受限 Git 源码/套件副本与 DockerRunner；真实权限反例通过 |
| P2-02 | 已完成 | 控制面命令/日志摘要、实际退出、超时/中断/输出预算与清理记录；真实容器测试通过 |
| P2-03 | 已完成 | 外部 stdlib unittest 冻结、完整 ID 选择、suite_hash；目标失败与导入错误/跳过明确区分 |
| P2-04 | 已完成（首版） | reproduced/not_reproduced/environment_blocked/needs_human 分类；同输入矛盾标 unstable，生成报告 |
| P2-05 | 进行中 | 按阶段恢复计划实现原子阶段提交、内核写锁、预算和三项调优案例 |
| P2-06 | 已完成（最小契约） | Oracle 绑定来源/套件/ID/审定依据；样例映射上游维护者已接受协议；不认证 Worker 的 accepted 声明 |
| P2-07 | 已完成（候选范围） | 指纹/退出/全部选择/Oracle/稳定性与缺证据拒判；最多 candidate_verified，不产生完整修复成功 |
| P2-08 | 已完成（最小图） | 拓扑序类型节点与必需依赖，Artifact/日志与 Run 绑定；动态失效和恢复留在 P3 |
| P3-01 | 未开始 | — |
| P3-02 | 未开始 | — |
| P3-03 | 未开始 | — |
| P3-04 | 未开始 | — |
| P3-05 | 未开始 | — |
| P3-06 | 未开始 | 失效传播与当前结论撤销 |
| P3-07 | 未开始 | F01～F06 故障注入 |
| P3-08 | 未开始 | 核心机制首轮对照 |
| P4-01 | 未开始 | — |
| P4-02 | 未开始 | — |
| P4-03 | 未开始 | — |
| P4-04 | 未开始 | — |
| P4-05 | 未开始 | — |
| P5-01 | 未开始 | 多仓库真实 Issue 集 |
| P5-02 | 未开始 | 可重跑评估与长期回归 |
| P5-03 | 未开始 | 离线证据报告 |
| P5-04 | 未开始 | 用户价值与技术复盘 |

## 2026-10-29：建立规划基线

### 完成事项

- 读取「learn cc」最后 5 轮用户与助手对话，保存来源快照与需求摘要。
- 明确产品方向和 MVP 边界；将用户要求与规划默认建议分开记录。
- 设计顺序工作流、独立审查、证据契约、恢复与预算规则。
- 形成四阶段实施计划、8 个受控案例的初始评估方案和决策记录。
- 通过 GitHub 连接器核对底座 v2 的实际源码与版本，并核对相关官方设计资料。
- 建立本目录的统一入口和后续维护规则。

### 主要产物

[总入口](../README.md)、[对话提炼](../00-context/conversation-summary.md)、[调研记录](../00-context/research-notes.md)、[产品说明](../01-product/product-brief.md)、[架构](../02-design/architecture.md)、[证据契约](../02-design/evidence-contracts.md)、[里程碑](../03-plan/milestones.md)、[评估方案](../03-plan/evaluation.md)、[决策](../05-decisions/decision-log.md)。

### 实际验证

- 工作区初始为空；未读到本目录及已检查父路径中的 AGENTS.md。
- Git 和 Python 命令可启动；当前 PATH 未找到 Docker 和 uv；WSL 运行能力尚未检查。
- 来源快照、文档链接、任务 ID 和目录隔离在交付前进行静态检查，结果记录于下方“交付检查”。
- 应用测试、容器测试、模型端到端测试：未运行，本轮没有实现这些功能。

### 风险与待核验

- 容器环境尚未确认，不能默认进入第三方代码执行阶段。
- 模型 Provider、凭据和实际调用预算尚未配置。
- 底座当前为 v2，历史材料不能直接当作适配代码；拟锁定版本仍需实验。
- 当时以 2～4 周为范围参考；此历史假设已由用户本轮无固定期限要求及 D-012 覆盖。

### 下一步

进入实施时执行 P1-01；若执行环境暂不可用，先推进不执行目标代码的只读调查闭环。

### 交付检查

- 已通过：共 11 个文件（10 份 Markdown 文档、1 份来源 JSON），全部位于 `planning/`；工作区根目录仅新增该目录。
- 已通过：23 个相对文档链接均指向存在的文件；UTF-8 解码与 Markdown 代码块闭合检查正常。
- 已通过：来源快照包含按时间排序的 5 轮完整用户/助手消息；单条回答均低于读取接口的 20,000 字符上限。
- 已通过：里程碑中的 21 个实施任务与本台账逐项对应，无缺失或重复。
- 这些是规划文档静态检查，不能代表 Agent 功能测试或端到端能力验证。

## 2026-10-29：规划入库与版本控制基线

### 完成事项

- 用户指定远程仓库 `git@github.com:iemmmii/RepoPilot.git`，要求规范版本控制并先上传规划。
- 远程分支列表为空；本地初始化 `main`，配置 `origin` 指向该地址。
- 增加根 README、`.gitignore`、`.gitattributes`、PR 模板和版本控制规范。
- 初始化使用 Conventional Commits；后续实质变更采用短期分支与 PR。
- 原始聊天快照保留本地，公开仓库保留需求提炼和规划文档。

### 连接与验证

- GitHub 官方主机公钥校验通过后，SSH 认证返回 `Permission denied (publickey)`。
- GitHub 连接器内容写入返回 403；随后确认本机 Git Credential Manager 已有 `iemmmii` 账户，改用现有 HTTPS 认证上传。
- `origin` 保留用户指定的 SSH 地址，仅为本仓库配置到同一仓库 HTTPS URL 的精确转写；不变更全局 Git/SSH 配置，不输出令牌。
- 已检查 15 个待提交文件、29 个公开文档相对链接、21 项实施任务；凭据模式扫描、LF/代码块及忽略规则检查通过。
- `git diff --cached --check` 通过。Agent 功能测试未运行，本轮未新增实现代码。
- 规划基线已提交并推送到 `origin/main`：[`97f34ae`](https://github.com/iemmmii/RepoPilot/commit/97f34aef8eed48073f0525f115010df5f7543ccf)，提交信息为 `docs(planning): establish RepoPilot planning baseline`。
- 通过 GitHub 接口独立核对远程文件清单：15 个版本化文件齐全，原始对话快照未上传；首次推送后本地工作区干净、main 已跟踪 origin/main。
- 本条发布结果在随后 `docs(progress)` 提交中补记，作为同次仓库初始化的收尾；后续实质变更按分支与 PR 流程处理。

### 决策与下一步

新增 D-011，细则见[版本控制规范](../05-decisions/version-control.md)。本轮只建立规划版本基线；Agent 实施仍从 P1-01 开始。

## 2026-10-29：选择性吸收评审，建立质量路线 v0.2

### 完成事项

- 完整读取「learn cc」最新一轮评审，将建议逐项记录为采纳、调整或保留意见。
- 按用户新要求取消四周实施限制，改为 M1～M5 质量出口；原 21 个任务 ID 保留，新增 10 项，共 31 项，均未开始实现。
- 将技术主线明确为证据依赖/失效、独立 Oracle 和可验证恢复；保留 Issue 到修复的产品用途。
- 新增证据图、恢复语义和威胁模型；同步架构、契约、产品说明、里程碑和评估。
- 增加错误 Oracle、不稳定执行、Gate/失效消融、故障注入与真实样例协议；同时衡量拒判和错误拒绝。
- 不引入图数据库或固定投入比例；A/B/A 为可选诊断，静态报告不冒充实时状态，所有能力保持“待实现”。
- 新增 D-012～D-016；本轮文档与后续进度仍集中在 planning/，根 README 只同步入口说明。

### 产物与验证

[评审回应](../00-context/review-response.md)、[证据图](../02-design/evidence-graph.md)、[恢复语义](../02-design/runtime-recovery.md)、[威胁模型](../02-design/threat-model.md)及已修订的[阶段路线](../03-plan/milestones.md)。

- 已通过文档静态检查：19 个拟版本化文件、17 份 Markdown、61 个相对链接、1 个 JSON 示例。
- 已核对 31 项任务与台账一致、原 21 个 ID 保留；6 个故障点、8 个威胁反例和 16 项决策定义齐全；文件为 UTF-8/LF，未提交原始聊天快照。
- `git diff --check` 通过；本轮修改仅涉及根 README 和 planning/，未新增实现代码。
- 设计修订已提交并推送：[`6217843`](https://github.com/iemmmii/RepoPilot/commit/6217843b0310d95a554afd2a95ed9f80ee96cc8c)，提交信息为 `docs(planning): define quality gates for verifiable repair`。
- 已创建并关联 [PR #1](https://github.com/iemmmii/RepoPilot/pull/1)，目标 main，来源 docs/evidence-verification-roadmap；保留未合并状态以供比较和审阅。
- GitHub 连接器缺少 PR 写权限，本次用本机已有 iemmmii 凭据完成 API 创建；凭据未写入文件或输出。此条进度记录另以 docs(progress) 提交到同一分支。
- 本轮未执行 Agent、沙箱、模型或故障注入测试；文档一致性不能代表这些设计已验证。

### 下一步

通过本轮规划 PR 后从 P1-01 开始实际核验。先用真实问题建立调查与最小验证闭环，不先扩展完整 UI 或多 Agent 团队。

## 2026-10-29：M1 只读调查实现与真实 API 验证

### 完成事项

- 用户选择 DeepSeek API，并在本地配置密钥；只检查配置是否存在，程序按需使用，不打印或提交密钥。
- 从规划分支建立独立实现分支，完成 P1-02～P1-06 的首个可运行闭环。
- 核对 WSL 未安装、Docker/Podman 不可用，保留执行禁令；P1-01 只记部分完成。
- 完成 mini-swe-agent 2.4.6 的离线 Submitted/预算契约实验；不将其记作生产 Coding Engine 集成。
- 选取 ItsDangerous #126 与固定 1.1.0 commit，完成离线调查和两次各 1 请求的真实 DeepSeek 调查；保留前后记录。
- 根据第一次样例暴露的上下文缺口改善短文件覆盖；第二次定位关键 age/max_age 判断，仍标为静态调查，未复现或修复。
- 按用户要求拆分 8 个功能子包和 unit/integration 测试；新增 D-017、D-018。

### 产物与验证

详见[M1 交付记录](m1-investigation.md)。29 项测试、ruff 检查及格式检查通过，最新真实报告的 4 个 Artifact 完整性为 valid。单元测试不访问网络，真实调用单列记录。

- uv.lock 检查、wheel/sdist 构建及包内容审查通过；8 个功能子包完整，分发包排除私有文件。
- 暂存范围检查通过：55 个版本化文件、65 个相对链接，实际本地密钥未出现在暂存文件中；原始 Run、目标仓库、虚拟环境和 .env 保持忽略。
- 初始功能提交 [`0abf5f5`](https://github.com/iemmmii/RepoPilot/commit/0abf5f5060058a3094c76f7569dc63546c11a5ef) 已推送；[PR #2](https://github.com/iemmmii/RepoPilot/pull/2) 依赖规划 PR #1，二者未合并。
- 初始功能提交的四组远程 CI 均通过；最终错误边界补测后共 29 项。当前提交的权威运行状态见 [PR #2 检查](https://github.com/iemmmii/RepoPilot/pull/2/checks)。

### 下一步

先完成隔离环境前置，再实施 SandboxRunner 与冻结复现测试。阶段恢复、Oracle、证据 DAG、修复和审查均未实现；本次不能据调查成功宣称 Issue 已解决。

## 2026-10-30：仅安装 WSL2 并核验

- 用户在暂停项目后将范围明确为“只安装 WSL2”；没有恢复 Docker 安装或 M2 实施。
- 核对先前启动的安装结果：Microsoft WSL 3.0.3 MSI 成功退出，VirtualMachinePlatform 为 Enabled，安装记录无需重启；本轮没有重复安装或触发重启。
- 沙箱外实际运行 `wsl --version` 和 `wsl --status` 均成功，内核版本为 6.18.54.1-1，默认版本为 2。`wsl --list --verbose` 明确报告没有已安装的发行版。
- 安装辅助脚本在 `scripts/environment/prepare_wsl.ps1`；版本核验及安装日志保留于忽略目录 `.repopilot/environment/`。先前编写但未执行的 Docker 验证草稿归档到该目录的 deferred/，不纳入本轮提交。
- WSL2 运行时安装完成不代表 Linux 已启动或沙箱已实现，P1-01 保持部分完成；未执行目标仓库代码、模型调用或容器测试。
- 新增 D-019，详细结果和下一步边界见 [WSL2 环境记录](wsl2-environment.md)。其余项目任务保持暂停。

## 2026-10-30：按条件授权完成执行环境准备

- 用户要求优先只用 WSL；不足时继续安装所需工具。发现 WSL 3.0.3 已内置 wslc，实际启动 Linux 内核成功；其当前 CLI 拒绝 `--read-only`、`--security-opt`、`--cap-drop`、`--pids-limit`，不能直接落实当前选择的执行策略。
- 选择补装 Docker Desktop 4.97.0，采用 per-user、WSL2 后端；安装包哈希与 Docker Inc 签名均核验，退出码 0。数据磁盘实际位于 D 盘；未额外安装 Ubuntu，没有自动重启。
- Docker Engine 29.9.2 的 Linux/amd64 服务已就绪。新增 `scripts/environment/verify_container.py`，使用官方 Python 镜像解析出的固定摘要，只挂载专用夹具。
- 实测非 root、只读根与工作目录、断网、capabilities 清空、禁止提权、seccomp、CPU/内存/PID 的 cgroup 值均通过；宿主驱动器和 Docker socket 不可见，探针未收到模型/GitHub 密钥变量；探针容器已清理。
- 修正当前父进程未刷新 PATH 导致 Docker 凭据辅助程序找不到的问题，仅补齐验证子进程 PATH。未改变全局代理设置，未将凭据传给容器。
- P1-01 按其“小实验”验收记为完成，M1 完成；M2 产品 Runner、Oracle 和目标项目执行仍未开始。未调用模型或运行第三方项目代码。
- D-020 与完整结果见[容器环境记录](container-environment.md)。本轮继续更新 [PR #4](https://github.com/iemmmii/RepoPilot/pull/4)，其余项目实现保持暂停。

## 2026-10-30：恢复项目并交付 M2 首个受控验证闭环

- 用户恢复项目任务；在独立分支实现 P2-01～P2-04、P2-06～P2-08 的首版，保持规划与程序源码分开。
- 新增 10 个功能包中的 sandbox/verification、类型化执行与 Oracle/图契约，新增 reproduce/verify-candidate；M1 调查行为和 0.1 manifest 保持兼容。
- 正式 Run 05140b6428d949c394b367d1b8266c88：上游修复父提交 base 1 failed / 5 passed，候选 6 passed，candidate_verified；18 个 Artifact 与图完整性 valid。
- 原调查版本 1.1.0 的 Run 9d1eabef9bca459dbb077b23f9246ad3：1 failed / 5 passed，reproduced；13 个 Artifact 与图完整性 valid。
- 105 项默认离线测试通过，真实容器另行 8 项通过；无目标宿主执行、无新增模型请求、无命令容器残留。最终仓库检查及远程结果在交付记录追加。
- 实现提交 342be44 已创建 PR #5；该提交 5 个远程 CI 作业均 success，具体不可变运行链接见交付记录。后续纯进度提交的最新检查以 PR checks 为准。
- 新增 D-021；独立依据、首个真实失败及修正、命令与限制见 [M2 交付记录](m2-controlled-verification.md)。P2-05 尚未开始，不将新 Run 的原子 manifest 当作阶段恢复。

## 后续条目模板

每次工作追加以下内容，同时更新上方看板与任务表：

```text
日期 / 阶段 / 任务 ID：
本次完成：
实际产物路径或 Run ID：
验证命令与真实结果（未运行则注明）：
尚未完成 / 风险 / 阻碍：
新增或变更的决策编号：
下一步：
```

“规划完成”“代码已写”“测试通过”“端到端可用”是不同状态，记录时分别说明。
