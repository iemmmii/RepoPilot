# WSL2 环境准备记录

日期：2026-10-30（Asia/Shanghai）。关联任务：P1-01。

## 本次范围

用户暂停原容器准备任务后明确要求“只安装 WSL2”。本次完成 WSL2 运行时核验，不继续安装 Docker，也不自动安装 Linux 发行版或恢复项目实现。

## 实际结果

| 检查 | 结果 |
| --- | --- |
| 先前 WSL MSI 安装 | 2026-10-29 成功退出，退出码 0 |
| 安装包校验 | 官方发布 SHA-256 匹配，Microsoft Corporation Authenticode 签名有效 |
| VirtualMachinePlatform | 安装记录为 Enabled |
| 安装记录重启要求 | false；没有安排或执行自动重启 |
| `wsl --version` | 成功，WSL 3.0.3.0，内核 6.18.54.1-1 |
| `wsl --status` | 成功，默认版本 2 |
| `wsl --list --verbose` | 返回“没有已安装的分发”，并非 Linux 启动验证通过 |
| Linux 启动、目标代码与隔离测试 | 未运行 |
| Docker | 安装程序此前仅下载，未执行；本次不安装 |

本轮核验时间为 2026-10-30 08:49（Asia/Shanghai）。WSL 查询在 Codex 沙箱内会返回 E_ACCESSDENIED；沙箱外查询成功，因此不将前者误判为系统安装失败。WSL1 未启用的提示不影响默认版本 2 的核验结论。

WSL 软件包版本 3.0.3 与发行版执行架构 WSL2 是不同概念。当前确认运行时已安装、默认版本为 2；由于尚无发行版，不能据此声称 Linux 环境或 RepoPilot 沙箱可用。

## 文件与验证

- `scripts/environment/prepare_wsl.ps1`：仅准备 VirtualMachinePlatform 和经哈希、发布者签名校验的 WSL MSI；要求管理员权限，不安装发行版、不安装 Docker、不自动重启。
- `.repopilot/environment/wsl-provision-result.json`：先前安装过程结果。
- `.repopilot/environment/wsl-msi.log`：本机 MSI 日志，不提交。
- `.repopilot/environment/wsl-verification.json`：本轮三条 WSL 查询的时间、退出码和输出，不提交。
- PowerShell 脚本语法解析、规划相对链接与 `git diff --check` 通过；本轮不重复安装系统组件，不运行与本次环境记录无关的产品测试。

## 后续边界

本次请求已完成。其余项目任务继续暂停。以后需要交互使用 Linux 时，再选择并安装发行版；进入 RepoPilot 复现和修复执行前，仍须实现并实际核验受限执行后端。WSL2 本身不能替代既定 SandboxRunner 的权限、网络、资源和凭据隔离要求，P1-01 保持部分完成。

依据：[Microsoft WSL 安装说明](https://learn.microsoft.com/en-us/windows/wsl/install)、[WSL 基本命令](https://learn.microsoft.com/en-us/windows/wsl/basic-commands)。上述安装结果以本机实际核验为准。
