# M2 首个受控验证闭环交付记录

日期：2026-10-30（Asia/Shanghai）。关联 P2-01～P2-04、P2-06～P2-08；范围受 [实施边界](../03-plan/m2-first-verification.md) 约束。

## 用户可用的变化

新增 `reproduce` 与 `verify-candidate`。前者验证固定 base 上的目标行为；后者在两个固定 Git ref 上运行同一冻结外部 unittest 套件。调查模式不自动执行命令；验证不调用模型，不生成补丁，也不修改用户工作区。

代码按功能组织：repository/materialize 生成源码与套件副本；sandbox/docker 管理受限执行和日志预算；sandbox/harness 是容器内 stdlib 适配器；verification 解析观察并判定；domain 保存正式契约及最小图；workflow、storage、reporting 负责可追溯交付。

## 执行与证据边界

- 只接受已缓存的 SHA-256 固定镜像和本机 Linux Docker endpoint；不自动下载、安装依赖或回退宿主执行。上下文中的 SSH、TCP 或远程命名管道拒绝作为本轮后端。
- 从 Git 对象读取完整受限快照，忽略脏工作区，排除 Git/工具缓存、.env、已知私有配置目录及 key/pem 文件；拒绝链接、子模块、跨平台不安全路径、大小越界和文件名冲突。指纹基于实际送入容器的文件，不冒称 Git tree 摘要就是执行环境。
- 仅挂载控制面生成的 workspace、suite、runner 三个目录，均只读；不传递宿主 HOME、Docker socket 或凭据。非 root、断网、只读根、cap-drop ALL、no-new-privileges、受限 tmpfs、CPU/内存/PID 限额固定在执行器内。
- 墙钟与合并输出预算有限；超限终止容器并清理子进程。输出保留有界字节前缀、实际收到的字节计数和截断标记，不能把截断记录当作正常通过。local 日志驱动另有界轮转，资源异常或清理失败拒绝通过。
- CommandEvidence 绑定 Run、argv/cwd、源码/套件/环境、控制面起止时间、Docker 容器名与可取得的容器时间、实际 ExitCode、终止原因、日志路径/摘要和清理结果。环境摘要同时包含镜像、内核、引擎、策略、Runner 与 harness 版本摘要。
- Oracle 绑定 Issue、suite_hash、完整的目标/回归 ID、来源及审定依据。控制面输入必须由操作者审核；schema 不认证外部声明者，Worker 写出的 accepted 字段不能直接成为可信审定。
- 观察区分 failed、error、skipped、xfailed 和空/重复/缺失选择；导入错误不是复现。Gate 复核来源指纹、实际退出码、全部必要 ID、Oracle 与稳定性矛盾，只输出本次范围下的分类。
- 最小 DAG 使用拓扑序类型节点，拒绝缺失/非法/环依赖；status 核对 Run、节点 Artifact 与命令日志引用。当前只判断保存产物的完整性，不检测 live 工作树变化或自动恢复旧阶段。

## Oracle 的独立来源

ItsDangerous #126 的负 age 要求在上游 [PR #133](https://github.com/pallets/itsdangerous/pull/133) 经维护者审查合并，固定修复为 `c30678d19e37011890e2374cca04f7789e101793`。本轮原创 unittest 套件将该协议映射为 1 项负 age 目标断言和 5 项相邻回归断言。

示例 Oracle 的 accepted 来源是已发布的上游需求/审查/测试映射，assessed_by 明确不是本用户或人工批准生成补丁。没有因本轮 fail/pass 自动升级状态，也没有扩展为时钟漂移容忍、完整项目回归或跨版本迁移保证。provisional/rejected 的控制测试均拒绝输出 candidate_verified。

为减少对照中的无关变化，正式候选对照采用修复父提交 `1a9b8d1f9968eb248bda69f39d373a6330b692ba`，与修复提交仅有上游列出的源码、测试和变更说明差异；另在 M1 最初调查的 1.1.0 固定提交单独复现，不伪称两个不同 base 相同。

## 真实 Run

| Run ID | 固定输入 | 实际结果 |
| --- | --- | --- |
| 05a68bf330764b249c0ba03eff852451 | 首次真实对照 | environment_blocked；Docker local 日志压缩不允许 max-file=1，目标未启动。保留两次失败命令记录，已修正为有界双文件轮转 |
| 26b66fde6d2e45abb4cd9478f7d66a05 | 修正后的早期对照 | candidate_verified；随后补全日志引用等记录字段；以以下最终 Run 为交付证据 |
| 05140b6428d949c394b367d1b8266c88 | 修复父提交 → c30678d；同一冻结套件 | base 1 failed / 5 passed，candidate 6 passed；candidate_verified，18 个 Artifact 与 DAG 完整性 valid |
| 9d1eabef9bca459dbb077b23f9246ad3 | M1 原始 1.1.0 base：6e6359864be6055860adf1e11d8bb0db69ff1840 | 1 failed / 5 passed；reproduced，13 个 Artifact 与 DAG 完整性 valid |

固定镜像：`python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb`。

套件 SHA-256：`eb9cdd96fd456f7f3c7b4a1fd313f1cba2f856abf2ea82de07f613c590932d1a`。时钟由 Signer 子类显式控制，无外部时钟服务或额外测试依赖。本轮模型请求为 0。

## 实际验证

- 105 项默认离线测试通过，8 项真实容器测试默认显式跳过；真实容器另行开启后 8 项全部通过，没有用跳过替代通过。
- 容器测试实际覆盖权限和 cgroup 值、三个输入挂载均不可写、宿主/凭据不传入、超时后删除容器与子进程、合并输出截断、中断记录、导入错误、跳过及空套件。
- 离线测试覆盖源码过滤/路径、快照稳定性、套件 CRLF 字节保持、Oracle 未审定、错误测试选择、跨输入/跨 Run 证据、错误返回码、稳定性矛盾、图合法性、持久化和显式 CLI。
- 首次新增集成测试因 Windows write_text 换行造成夹具哈希不匹配；夹具改为显式字节写入。产品冻结器始终校验实际字节，未通过放宽哈希来绕过差异。
- 新增独立 Linux 容器 CI 作业；先显式准备固定公开镜像，再运行 tests/container。远程 CI 结果另行记录，不以本地结果冒充。
- 最终按 repopilot-command- 前缀查询，无本轮残留命令容器。没有在宿主导入或执行目标项目，没有调用模型。
- Ruff 检查与格式检查通过（49 个 Python 文件），uv.lock 离线一致性核对通过；wheel/sdist 离线构建成功，38/57 个分发条目包含新 harness/Gate，未包含 .env、.repopilot、虚拟环境、安装包或原始对话。uv 的缓存位于源目录警告已通过实际包内容核查排除。
- 根入口及 20 份规划文档的 UTF-8/相对链接检查通过，共 82 个相对链接；示例 Oracle 的 suite_hash 与实际文件字节匹配，git diff 检查通过。
- 环境 PR #4 在本轮期间合并；M2 分支已基于 fd0c916 主干基线，不依赖未合并的环境 PR，不重写已共享提交。
- 实现提交 [`342be44`](https://github.com/iemmmii/RepoPilot/commit/342be44649993e799e255e719bececa8ce55f463) 已推送，已创建 [PR #5](https://github.com/iemmmii/RepoPilot/pull/5)，目标 main，尚未自动合并。远程检查的当前状态以 [PR #5 checks](https://github.com/iemmmii/RepoPilot/pull/5/checks) 为准；四组常规测试和独立 Linux 容器作业均已配置。
- 实现提交 342be44 的 [CI 运行 40987237364](https://github.com/iemmmii/RepoPilot/actions/runs/40987237364) 实际完成且 5 个作业全部 success：Windows/Linux × Python 3.11/3.13 四组常规检查，以及独立 Linux 真实容器检查。本条是该实现提交的快照；后续纯进度提交的检查另以 PR 当前 head 为准。

## 使用与剩余限制

根 README 提供已知样例命令。恢复以前的 Run、读取或复用 running/orphan 记录尚未实现；本轮仍为新 Run 单写入者存储，0.1 调查 manifest 保持可读，验证 manifest 为 0.2。不要把普通 Artifact 检查点说成 P2-05 的阶段恢复。

套件目前支持外部 stdlib unittest，固定精确 ID，不自动运行仓库自带 pytest 配置、依赖安装或所有测试。缺依赖、错误或必要跳过均阻止验收。未执行完整项目回归、语义补丁审查或模型修复，resolved_verified 不可产生。

首版不支持 subTest 聚合；出现这类观察时按协议/选择不一致拒判，不悄悄忽略子测试。

同解释器内的主动恶意代码可能篡改测试工具，容器与 JSON 协议不能证明测试语义真实性；此版只支持受控公开 Python 样例，不覆盖公开多租户服务。单次对照不证明永不 flaky，稳定性通常为 not_checked；相同受控输入已出现矛盾时显式拒判为 unstable/needs_human。

下一项为 P2-05 的阶段级检查点、恢复和 3 个调优案例；然后进入 P3 的模型修复、变更失效与 F01～F06 故障注入。
