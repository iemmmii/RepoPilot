# M2 首个受控验证闭环

日期：2026-10-30。用户已恢复项目任务；本轮在 codex/m2-controlled-verification 实现。开始时依赖环境 PR #4，期间该 PR 已合并；交付分支接到 fd0c916 主干基线，不自动合并本轮实现。

实施后的结果与剩余范围见 [M2 交付记录](../04-progress/m2-controlled-verification.md)。为控制无关差异，正式对照改用已知修复父提交，同时单独在原 1.1.0 base 复现；原因和所有 Run 均保留。

## 交付边界

先实现 P2-01～P2-04 的可运行闭环，并接入 P2-06～P2-08 所需的最小 Oracle、Gate 和证据关系。不调用模型生成修复；通过固定 base/candidate Git ref 验证已知候选。生产 Coding Engine、工作树补丁循环、阶段恢复和多案例评估仍属后续任务。

控制面从 Git 对象生成受限源码副本，排除密钥、Git 元数据、链接和越界路径；冻结外部 unittest 套件，绑定实际送入容器的源码、套件、镜像与策略摘要。测试仅在已缓存的固定摘要镜像内执行，不自动安装依赖或回退宿主运行。

Docker 执行器强制本机 Linux 引擎、非 root、断网、只读源码/套件/根文件系统、禁止提权、capability 裁剪、CPU/内存/PID 限额及墙钟/输出预算。由控制面记录实际进程与容器状态、日志和清理结果，超时与输出超限不伪装成正常测试失败。

冻结 unittest 适配器分别报告行为断言失败、导入/执行错误、跳过及空套件；Gate 核对明确的目标和回归测试 ID，不能仅凭返回码判定复现。Oracle 保留来源与审定：provisional/rejected 不支持完整成功，accepted 需要独立依据记录。verify-candidate 范围最多输出 candidate_verified，不输出 resolved_verified。

## 验证安排

- 离线测试覆盖快照路径/链接/密钥排除、实际送入文件的指纹、非法或缺失证据、跨快照/套件误绑定、空测试/跳过/导入错误、错误与 provisional Oracle，以及超时/输出/清理分支。
- 在本机真实 Docker 运行受控权限探针、超时与大量输出样例；确认无残留容器、控制面证据不可写、凭据不传入。
- 使用 ItsDangerous #126 的固定 1.1.0 base 和已知修正候选，固定时钟并加入有效期边界、过期及无 max_age 的回归断言。先核对上游需求和修复来源，再决定 Oracle 审定状态；不得因本轮自写测试 fail/pass 就自称需求已独立确认。
- 保留失败、中断和环境受阻产物；不声称任意恶意 Python 项目无法篡改同解释器内的测试工具，首版只支持受控公开 Python 样例。
- 更新 planning/ 的真实进度、限制与验证结果；源码按 repository/sandbox/verification/workflow/storage/reporting 的职责分文件夹。

## 后续保留

P2-05 的 resume、故障注入与 3 个调优案例不以普通新 Run 保存代替。P3 的变更失效、完整修复 Gate 与故障恢复在独立工作单元实现。首个闭环有完整命令证据和输入绑定后，再扩展能力。
