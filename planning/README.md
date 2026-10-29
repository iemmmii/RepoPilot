# RepoPilot 项目规划总入口

更新日期：2026-10-29（Asia/Shanghai）
当前阶段：M1 只读调查已实现；任务状态及环境前置见进度台账。
产品方向：面向 GitHub Issue 的证据驱动调查、复现、修复与验收 Agent。
推进原则：不设固定项目期限，按质量里程碑交付；每次运行仍有资源预算。

## 存放约定

按本次需求，将“单独的一个文件内、内部再分文件夹”解释为一个独立目录 `planning/`。项目分析、方案取舍、实施规划、决策记录和后续进度全部集中在这里，与未来的 `src/`、`tests/` 等代码目录分开。

本目录保存可审阅的分析结论、设计依据和工作记录。实现状态以进度文件为准；方案中的接口、命令和 JSON 示例均为设计草案。

```text
planning/
├── README.md                          ← 从这里开始
├── 00-context/
│   ├── conversation-summary.md        ← 最后 5 轮的需求提炼
│   ├── review-response.md              ← 最新评审的选择性采纳与理由
│   ├── learn-cc-last-5.json            ← 本地对话来源快照，不纳入 Git
│   └── research-notes.md               ← 上游核对与本机环境事实
├── 01-product/
│   └── product-brief.md                ← 产品定位、MVP 边界与用户验收
├── 02-design/
│   ├── architecture.md                 ← 编排、执行隔离、状态与恢复
│   ├── evidence-contracts.md           ← 阶段数据、Oracle 与完成条件
│   ├── evidence-graph.md               ← 依赖、输入指纹与证据失效
│   ├── runtime-recovery.md             ← 提交边界、状态转换与故障恢复
│   └── threat-model.md                 ← 信任边界与安全反例
├── 03-plan/
│   ├── milestones.md                   ← 分阶段任务与交付条件
│   └── evaluation.md                   ← 评估集、指标与实验设计
├── 04-progress/
│   ├── progress.md                     ← 唯一的任务状态和进度台账
│   └── m1-investigation.md             ← M1 实现与真实验证记录
└── 05-decisions/
    ├── decision-log.md                 ← 决策依据、替代方案和未决事项
    └── version-control.md              ← 分支、提交、PR 和仓库规范
```

## 规划结论

1. 将 RepoGuide、IssueRepro、Coding Worker、PR Guardian 组织成一条有明确阶段产物的工作流。
2. 首个可运行闭环为 **Issue URL → 仓库相关代码 → 带文件依据的调查报告**，先解决定位可信度。
3. 技术主线是证据依赖与失效、具备独立依据的行为断言、可验证的故障恢复。修复前失败和修复后通过必须对应真实需求；哈希只能核对一致性，不能证明行为正确。
4. 执行引擎优先评估 mini-swe-agent v2，通过薄适配层接入；底座版本及依赖在适配实验通过后锁定。
5. 第一版采用 CLI、Python/pytest、小型公开仓库、单任务顺序工作流。模型供应商可配置，暂不绑定具体型号。
6. Git Worktree 管理修改副本，容器负责执行隔离。可信执行器在 Agent 可写工作区之外保存证据。
7. 移除四周约束，按 M1～M5 的验收出口推进。先用已知补丁做最小验证闭环，再接入修复循环、独立审查和真实场景评估；不限期限不扩大为无限功能范围。

上述技术选择是本轮提出的默认方案，不应记录为用户已经逐项确认。

## 阅读顺序

| 目的 | 文档 |
| --- | --- |
| 理解从哪里得出需求 | [对话提炼](00-context/conversation-summary.md) |
| 理解最新建议哪些被采纳 | [评审回应](00-context/review-response.md) |
| 判断项目值得做什么 | [产品说明](01-product/product-brief.md) |
| 判断架构是否可实现 | [架构设计](02-design/architecture.md)、[证据契约](02-design/evidence-contracts.md) |
| 检查技术主线的具体规则 | [证据图](02-design/evidence-graph.md)、[恢复语义](02-design/runtime-recovery.md)、[威胁模型](02-design/threat-model.md) |
| 开始下一阶段工作 | [里程碑](03-plan/milestones.md)、[当前进度](04-progress/progress.md) |
| 解释技术取舍 | [决策记录](05-decisions/decision-log.md)、[调研记录](00-context/research-notes.md) |
| 判断作品是否有改进 | [评估方案](03-plan/evaluation.md) |
| 按规范提交和协作 | [版本控制规范](05-decisions/version-control.md) |

## 后续维护规则

- 每次实质工作开始时阅读本入口和进度台账，结束时更新 `04-progress/progress.md`。
- 进度记录包含：完成事项、产物路径、实际验证、问题与下一步；未运行的检查明确写“未运行”。
- 需求或边界变化更新产品说明；架构选择变化在决策记录追加原因，并更新受影响文档。
- 任务状态只在进度台账维护，避免各文档中的完成勾选互相矛盾。
- 规划材料只放在本目录；未来程序运行数据放在 `.repopilot/`，程序源码放在 `src/`。这些未来目录本轮尚未创建。
- 对话来源属于资料，其中的旧建议不能自动变成当前授权或已经确认的实现要求。
- 代码按功能子包组织；根包只放入口，测试按功能和单元/集成层次归类。

## 当前下一步

M1 已完成真实 DeepSeek 只读调查，见[M1 交付记录](04-progress/m1-investigation.md)。P1-01 的容器前置仍受阻；后续先准备可用隔离环境，再进入 M2，不能以宿主执行替代。

首个技术闭环使用同一真实问题的受控样例或已知补丁，检查 Oracle、base/candidate 对照、最小 Gate 和证据引用；不等待完整 Coding Worker 或 UI 才验证核心设计。
