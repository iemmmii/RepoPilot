# 阶段产物与证据契约

状态：数据设计草案 v0.1；字段在实现时形成正式 Schema。下文示例是设计数据，没有实际运行结果。

## 一次运行的产物布局

未来运行数据使用 `.repopilot/`，与项目管理目录 `planning/` 分离：

```text
.repopilot/
├── repositories/                         # 控制面仓库缓存 / managed worktree
└── runs/<run_id>/
    ├── manifest.json                     # 最后可靠检查点与阶段引用
    ├── events.jsonl                      # 生命周期事件
    └── stages/
        ├── ingest/attempt-001/issue.json
        ├── analyze/attempt-001/repo_context.json
        ├── analyze/attempt-001/investigation.md
        ├── reproduce/attempt-001/reproduction.json
        ├── reproduce/attempt-001/repro_tests/...
        ├── patch/attempt-001/patch.diff
        ├── verify/attempt-001/test_results.json
        ├── verify/attempt-001/commands/...
        ├── review/attempt-001/review_report.json
        └── report/attempt-001/
            ├── acceptance_coverage.json
            ├── report.md
            └── pr_draft.md
```

各执行阶段均可含 `commands/`；图中只画出 verify 的一个例子。未开始的阶段不伪造文件。大日志可截断展示，但保存完整文件的路径、大小、哈希及截断标记。日志和可导出产物做凭据脱敏。

## 共用关联字段

| 对象 | 主要字段 | 不变条件 |
| --- | --- | --- |
| Run | `schema_version, run_id, requested_scope, issue_snapshot_hash, base_commit, execution_status, outcome, budget` | 输入范围与目标 commit 可追溯 |
| Artifact | `artifact_id, stage, attempt, relative_path, sha256, created_at` | 路径限定在 Run 根目录；引用的内容必须存在 |
| RepoContext | `base_commit, source_digest, relevant_files, symbols, candidate_test_commands, hypotheses` | 路径和代码引用由程序检查；假设与事实区分 |
| Environment | `image_digest, python_version, dependency_lock_hash, policy_version` | 影响结果的环境变化导致旧验证失效 |
| CommandEvidence | `evidence_id, argv_or_shell, cwd, started_at, ended_at, exit_code, termination_reason, stdout_ref, stderr_ref, snapshot_id, environment_id` | 由可信 Runner 生成；超时和未执行不得伪装成退出码 0 |
| TestResult | `command_evidence_id, suite_hash, selected_nodeids, collected, passed, failed, skipped, xfailed, status` | 测试选择、测试内容和代码版本都绑定 |
| Reproduction | `status, expected_behavior, observed_behavior, criterion_ids, failure_evidence_ids, repro_suite_hash` | `reproduced` 必须关联目标断言失败 |
| Review | `snapshot_id, diff_hash, findings, criterion_assessments, verdict` | 每项发现有路径/依据；更换候选后审查失效 |

`snapshot_id` 包含 base commit 与候选源码摘要；单写 HEAD 不足以表示未提交修改。`suite_hash` 表示冻结验证套件内容。时间保存 UTC 标准时间，界面可按 Asia/Shanghai 显示。

命令返回码必须取自执行进程；模型只能引用已存在的 `evidence_id`。Provider 用量缺失、未获得的字段使用 `null` 和原因，不补造数值。

## 验收项与覆盖关系

一个验收项至少包含：

- `criterion_id`、需求描述、来源位置和是否为必要条件。
- `origin`：Issue 明示 / 用户补充 / 模型推断。推断项保持该标记，不得冒充用户要求。
- `verification_method`：确定性测试 / 静态检查 / 语义审查 / 人工确认。
- `status`：`unverified / satisfied / failed / blocked / needs_human`。
- 证据 ID 列表、适用版本、局限说明。

在正式修复前形成版本化的验收项集合。模型不能为让结果通过而删减必要条件；新需求或人工澄清生成新版本，并使受影响验证失效。需求含糊时可先完成调查，将含糊项保留为 `needs_human`。

示例覆盖关系：

```json
{
  "schema_version": "0.1-draft",
  "example_only": true,
  "criterion_id": "AC-001",
  "description": "过期 Token 返回 401",
  "origin": "issue_explicit",
  "required": true,
  "verification_method": "test",
  "status": "unverified",
  "baseline_evidence_ids": [],
  "candidate_evidence_ids": [],
  "limitations": []
}
```

这里空证据只能对应未验证。示例不创建貌似真实的通过记录。

## 复现分类

| 分类 | 判据 | 不能因此宣称的内容 |
| --- | --- | --- |
| `reproduced` | 在固定 base/环境下，目标断言按预期方式失败 | 所有 Issue 症状都已覆盖 |
| `not_reproduced` | 环境可执行，但目标失败未出现或证据不充分 | Issue 不存在 |
| `environment_blocked` | 安装、导入、资源、权限、网络等使目标行为无法验证 | 已复现业务 Bug |
| `needs_human` | 预期行为或复现 oracle 不明确 | 可以自动继续修复并验证 |

非零退出码只是信号。需检查测试结果与失败位置，区分行为断言失败、测试收集问题和执行器异常。当前 pytest 的退出码定义参考[官方文档](https://docs.pytest.org/en/stable/reference/exit-codes.html)。

## 完成闸门

第一版完整修复需要同时满足以下条件：

1. Issue、base、环境、冻结测试和候选源码都有可追溯标识。
2. 至少一个目标行为在 base 上失败，失败与 Issue 的必要条件对应。
3. 同一冻结测试在当前候选上执行且通过，没有被跳过或改弱。
4. 指定回归集确实执行且满足预定义策略；数量变化和新增 skip/xfail 被检查。
5. 必要验收项都有适用当前版本的证据；语义项有审查结论或所需人工判定。
6. PR Guardian 没有未处理的阻断发现，代码与测试变更均在审查范围。
7. 原始证据完整，且不存在候选变更导致的过期结果。

满足后才输出 `resolved_verified`，并列明“在这些测试和环境范围内”。独立审查的置信判断无法替代缺失的确定性测试。

只读调查与复现模式各自有范围验收，不强制执行后续修复。Run 可以完整交付调查报告，同时仍无法判断 Bug 是否存在。

## 防止虚假通过

| 风险 | 契约约束 |
| --- | --- |
| 修改代码之后引用旧测试 | 源码摘要不同则结果过期 |
| 删除测试后全绿 | 冻结套件在控制面保留，并比较测试选择与内容 |
| pytest 没收集到测试 | 检查 collected 和目标 nodeids；空集不能通过 |
| 所有目标测试被跳过 | 必要断言必须实际执行；skip/xfail 单列 |
| 依赖失败被说成复现成功 | 复现分类要求目标行为证据 |
| 模型捏造日志 | 只接受可信 Runner 注册的证据 ID |
| 模型看到自己的解释后自我认可 | Reviewer 使用独立上下文，Gate 独立读取结构化证据 |
| 因预算停止被记为完成 | 执行状态与业务结果分别保存 |

这些规则提高在可控仓库中的结果可靠性，不构成对任意恶意测试代码的真实性证明。

## 最终报告最少包含什么

Issue 来源与版本、当前执行状态和业务结果、代码定位依据、复现步骤及原始日志引用、修改 Diff、修复前后测试对照、验收覆盖表、审查发现、未验证范围、消耗与停止原因、可恢复位置。

报告从结构化产物生成事实部分。模型可整理解释，但不能覆盖计数、状态或添加未注册的测试结果。
