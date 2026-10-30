# M1 只读调查交付记录

日期：2026-10-29。范围：P1-02～P1-06 的只读闭环，以及 P1-01 的环境、底座和模型可行性核验。容器前置仍未满足，不能把它记为已准备好执行目标项目。

更新说明（2026-10-30）：以下保留交付当日记录；后续已完成 WSL2 + Docker Desktop 环境与受限容器探针，见[容器环境记录](container-environment.md)。产品仍保持只读，生产 SandboxRunner 尚未实现，当前任务状态以[进度台账](progress.md)为准。

## 实际交付

- `doctor`：检查 Git、容器命令、WSL、模型凭据是否存在；不打印或测试密钥。
- `investigate`：读取 GitHub Issue URL 或本地 Issue JSON，固定 Git commit，静态检索源码和 Python 符号，调用 DeepSeek 或显式离线基线。
- 引用校验：只接受已提供上下文内的路径和行号；非法引用使 Run 失败，保留已生成产物。
- `status`：核对保存的 Artifact 路径、大小及 SHA-256；不能用它推断工作区当前行为或问题已解决。
- 每次运行有独立目录、manifest、Issue、repo_context、analysis 和报告；失败也保存状态。阶段恢复和 Evidence DAG 还未实现。
- 源码按功能分为 8 个子包；根包仅保留入口与版本，测试分为 unit 和 integration。
- `pyproject.toml`、`uv.lock`、隔离环境、格式/静态检查，以及跨 Windows/Linux、Python 3.11/3.13 的 CI 定义。

## 环境与底座实验

当前控制端为 Windows、Python 3.13.5。未发现 Docker/Podman 命令及常见安装路径；WSL 状态明确返回未安装。因此当前产品始终禁止执行目标项目代码，后续隔离复现需要先完成环境准备。

mini-swe-agent 固定为 2.4.6，下载在 `.repopilot/engine-probe/`。`scripts/probe_engine.py` 用合成 Model/Environment 验证 Submitted、LimitsExceeded、动作接口和轨迹保存，均通过；外部模型请求和 shell 命令均为 0。

该实验使用独立下载包和控制端已有基础依赖，不是生产 Coding Engine 集成，也不是沙箱测试。M1 直接使用窄 Provider 接口完成只读调查；M3 再接入有沙箱约束的 Coding Engine，不采用宿主 LocalEnvironment。

## 真实样例与结果

开发样例：[ItsDangerous Issue #126](https://github.com/pallets/itsdangerous/issues/126)。固定 base 为 1.1.0 对应提交 `6e6359864be6055860adf1e11d8bb0db69ff1840`。目标仓库以 no-checkout 方式保存在忽略目录，只读取 Git 对象，没有安装依赖或执行目标源码。

| 运行 | 结果 | 模型消耗与观察 |
| --- | --- | --- |
| `7b68c84a2ebe44a5bf5a99f7ca774e3f` | 离线调查完成 | 模型请求 0；显式标为 lexical 基线 |
| `25d42b7dc6d84f01977ef83f565e3928` | 首次真实 DeepSeek 调查完成 | 请求 1；输入 7580、输出 839 Token；引用有效，但短窗口没有包含关键 unsign 判断 |
| `150716e9417546598376085799917729` | 改善短文件覆盖后完成 | 请求 1；输入 9651、输出 455 Token；定位 `src/itsdangerous/timed.py:84–93` 的 age/max_age 判断；4 项引用均在提供的上下文内 |

费用未知，不推算为零。模型配置使用 `deepseek-flash`；这是服务别名，尚未固定服务端权重版本。第二次调查补全了源码上下文，不能据单一样例宣称普遍定位率提高。

最新报告和 4 个 Artifact 的完整性核对为 valid。报告结果均为 investigated、tests_executed=false。关于未来时间戳的判断仍是静态调查假设，未声称已复现或已修复；时钟偏差容忍策略须在后续 Oracle 阶段审定。

## 实际验证

- 29 项自动测试通过，含脏工作区隔离、不导入目标 Python、排除已跟踪 `.env`、路径/行号校验、异常/预算、失败保存、产物损坏与越界、HTTP/JSON 错误和凭据转发边界；最终审查另覆盖非对象 GitHub JSON 和保留检查点文件名。
- ruff check 与 format 检查通过，测试按功能目录重组后再次通过。
- 测试在本机项目忽略目录内使用独立临时根；首次默认临时目录受当前 Windows 沙箱限制，后续显式指定新目录，未放宽产品权限。
- 初始功能提交 `0abf5f5` 的 Windows/Linux、Python 3.11/3.13 四组远程 CI 均通过；当前提交结果以 [PR #2 检查](https://github.com/iemmmii/RepoPilot/pull/2/checks) 为准，不用本地通过代替远程结果。
- uv.lock 一致性、wheel/sdist 构建和包内容审查通过；8 个功能子包齐全，分发包不包含密钥或运行数据。

## 在当前工作区使用

项目环境已经建好，无需全局 uv 即可运行：

```powershell
.venv\Scripts\python -m repopilot doctor
.venv\Scripts\python -m repopilot investigate --issue-file examples/issues/itsdangerous-126.json --repo .repopilot/repositories/itsdangerous --ref 6e6359864be6055860adf1e11d8bb0db69ff1840 --provider lexical
.venv\Scripts\python -m repopilot status .repopilot/runs/150716e9417546598376085799917729
```

新环境用 `uv sync --locked`。首次准备样例时可用 `git clone --no-checkout https://github.com/pallets/itsdangerous.git .repopilot/repositories/itsdangerous`；已有目录时先检查，不覆盖。

DeepSeek 密钥从当前目录的本地 `.env` 加载，不提交。每次调查最多 1 次模型请求、最多 2500 输出 Token、请求超时 60 秒；不自动重试。Issue/源码上下文有大小限制，候选测试命令只展示，不执行。

## 已知边界与下一步

Git 快照只代表固定提交，不包含未提交或未跟踪代码。检索有文件/字节/上下文上限，引用有效不代表原因判断正确。当前摘要是 Git tree manifest 的 SHA-256，并非后续 SandboxSnapshot 的完整执行环境指纹。

存储只支持新 Run 与原子 manifest，不支持阶段级 resume、图失效或断电事务。下一步先完成容器前置，再进入 P2-01～P2-03 的受限执行与冻结复现测试。不能绕过沙箱在宿主执行第三方代码。
