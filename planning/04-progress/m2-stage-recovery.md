# M2 阶段恢复与初始评估交付

日期：2026-10-30（Asia/Shanghai）。任务 P2-05，提前验证 P3-07 的部分恢复反例。

## 已实现

新增 `resume` 与 `evaluate`，代码仍按 storage、workflow、sandbox、evaluation 等功能分目录，规划集中在 planning/。

0.3 验证 manifest 保存 inputs/base/candidate/assess 的逐次尝试、输入摘要、提交产物、容器名与预算。阶段先登记 running，所有产物写完后一次 manifest 替换才登记完成；未提交文件保留为 orphan，重跑使用新的 attempt 文件名，已提交记录不覆盖。图和报告引用始终绑定本次已提交的 Artifact。

内核文件锁在 Windows 使用 CRT、Linux 使用 flock，锁文件保持稳定且不删除；进程退出由 OS 释放，不根据 PID/时间猜测或抢占。只有取得锁后才验证并恢复，旧 Run 的 0.1/0.2 查询仍可用；新调查仍保持 0.1 文件格式，未混入恢复字段。

恢复重新构建受限源码与套件，核对冻结 Issue、Oracle、Git ref/源码、套件、策略、镜像、Runner 和 harness 摘要。输入变化或证据损坏拒绝复用，不改写历史结果。外部 Issue 的最新内容不在 resume 中自动联网获取；这里核对的是本次冻结来源。

命令创建前登记唯一容器名；恢复核对 managed 标签后只清理自己的 running/failed/interrupted 尝试容器。默认最多 6 次命令预留、总计 1200 秒保守时间预留，单命令预算仍由策略限制。不确定尝试也计入预算，不冒充实际运行时长或模型费用；本轮模型请求均为 0。

## 实际验证

- 默认离线套件 **119 passed / 12 skipped**；另行开启真实 Docker 后 **12 passed**。默认跳过未计为容器通过。
- 子进程调用 os._exit，真实验证 F01（命令结束、产物提交前）、F03（产物已写、阶段提交前）、F04（阶段提交后）。真实 Docker 的 F01/F03 恢复后命令总预留为 3；F04 为 2，已提交 base 不重复运行。
- 离线进程实验额外覆盖最终 assessment 已提交但通知未完成，恢复后不重复命令；覆盖锁争用、预算不能重置、输入变更拒绝、损坏拒绝和失败清理后重试。
- 真实测试核对具名运行容器的 ownership 后删除，原有权限/资源/超时/中断/输出上限与错误分类测试仍通过。
- 首轮真实测试发现 Docker 引擎已停止，产品如实失败，没有降级宿主执行；启动已安装引擎后继续核验。
- 真实恢复曾发现策略默认 int 60 与 JSON 读回 float 60.0 的指纹差异；已通过验证默认值并冻结策略修正，另加 JSON 往返回归，不放宽输入比对。
- Ruff 检查与格式检查通过（55 个 Python 文件）；uv.lock 离线核对、wheel/sdist 构建通过。42/62 个分发条目包含新恢复/评估模块，不含 .env、.repopilot、虚拟环境或安装包。23 份 Markdown 的 UTF-8 与 89 个相对链接通过。
- 本轮结束前按 repopilot-command- 前缀核对，无残留命令容器。版本控制使用 [PR #7](https://github.com/iemmmii/RepoPilot/pull/7)，最终检查结果以当前 head 的 checks 为准；草稿阶段不自动合并。

## 三个受控调优案例

正式评估 ID：`5485792e6ee74dfbb12139e8bf403f74`，协议 `repopilot-controlled-cases-v1`。

| 案例 | 预设协议 | 实际结果 | Run ID | 命令预留 |
| --- | --- | --- | --- | --- |
| C01 | 过期凭据返回 401，有效凭据仍为 200 | candidate_verified | c7e28e28812f4d4ca858df0b3edde28b | 2 |
| C02 | 空输入平均值为 0，非空保持平均行为；明确把目标 ZeroDivisionError 转成断言失败 | candidate_verified | 3ef41dda404c437cb436a40b3c15389a | 2 |
| C03 | 唯一命名依赖不可获得；导入错误不能算复现 | environment_blocked | 3b40ad372b784e668e687dd790e2676d | 1 |

三个 Run 的 Artifact 完整性 valid；分类 3/3 符合预设协议。是小型受控调优数据与已知候选验证，不是三个真实公开 Issue、模型生成修复率或总体有效性估计。没有 resolved_verified 声称，完整修复虚假成功率为 N/A。

随后真实调用 C01 的 resume：命令预留 **2 → 2**，Artifact 列表完全不变，仍为 candidate_verified / valid。原始清单保留于忽略目录 `.repopilot/evaluations/5485792e6ee74dfbb12139e8bf403f74/summary.json`；补充恢复汇总在 `.repopilot/environment/m2-recovery-live.json`。早期开发评估 `8986e0458fc4456189d77af0d1f0fe38` 保留，但不用作最终恢复证据。

评估发生基础设施异常时，案例仍进入结果清单，并保留可取得的失败 Run 路径；不会删除失败案例来改变分母。

## 范围与下一步

保证范围是本机文件系统、单写入者、进程中断。未承诺任意断电、分布式 exactly-once 或模型请求计费去重。旧的 orphan 文件与执行目录保留以供排查，不自动删库或 prune。主动恶意 Python 项目的测试真实性限制仍然存在。

M2 的剩余出口已补全。下一阶段为 M3：managed worktree/候选管理、受限 Coding Engine、模型修复、证据失效与完整 Gate。F02、F05/F06 的完整真实故障矩阵及动态失效仍按 P3 继续，不以本轮几个退出点宣称恢复研究结束。

锁语义依据：[Python msvcrt](https://docs.python.org/3/library/msvcrt.html)、[Python fcntl](https://docs.python.org/3/library/fcntl.html)。结论以本机测试与后续跨平台 CI 实际结果为准。
