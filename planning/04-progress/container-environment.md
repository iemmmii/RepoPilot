# 执行环境选择与容器验证

日期：2026-10-30（Asia/Shanghai）。关联任务：P1-01；后续产品接入：P2-01。

## 选择依据

用户要求优先只用 WSL；不满足时继续安装所需工具。普通 WSL 发行版默认能够访问 Windows 驱动器并启动 Windows 程序，不能直接作为 RepoPilot 的受限执行器。

本机 WSL 3.0.3 已包含 wslc，不再假定必须先安装其他引擎。实际核验如下：

| 路线 | 实际观察 | 本次决定 |
| --- | --- | --- |
| 普通 WSL 终端 | 当前未安装用户发行版；其默认宿主集成不能满足项目的文件和权限边界 | 不用于运行目标项目 |
| WSL 自带 wslc | 能启动 Linux 内核；当前 CLI 拒绝 `--read-only`、`--security-opt`、`--cap-drop`、`--pids-limit` | 本轮不选作标准 Runner 后端 |
| WSL2 + Docker Desktop | 安装和 Linux 引擎就绪，受限探针通过 | 采用此环境，后续接入 Runner |

这不表示 WSL 无法通过原生 API 或定制安全层实现类似约束。本轮选择已有标准运行时，以便直接落实相同策略，避免新增一套需独立维护和审查的权限实现。

## 安装与配置事实

| 项目 | 结果 |
| --- | --- |
| WSL | 3.0.3.0，默认版本 2 |
| 实际启动内核 | 6.18.54.1-microsoft-standard-WSL2 |
| Docker Desktop | 4.97.0 / build 244584，per-user 安装，退出码 0 |
| 安装包来源与校验 | Docker 官方分发；SHA-256 匹配，Docker Inc Authenticode 签名有效 |
| Docker Engine | 29.9.2，Linux / amd64，context 为 desktop-linux |
| Docker 数据根 | D:\RepoPilotContainerData\docker-desktop；已确认 disk/docker_data.vhdx 与 main/ext4.vhdx 实际存在 |
| 其他 Linux 发行版 | 未额外安装 Ubuntu 等用户发行版；Docker 使用自身 WSL 后端 |
| 重启 | 没有安排或执行自动重启 |

安装包 SHA-256：`2668273F82B342A058A28F9AB53EA7BDDDE10BB6D51307CE2EC54C2D36459744`。

评估 wslc 时创建了 `%LOCALAPPDATA%/wslc/settings.yaml`：会话上限 2 CPU / 2GB，动态磁盘上限 32GB，存储根为 D:\RepoPilotContainerData，关闭 hostLoopback 名称。此前没有该配置或活动会话，没有覆盖已有设置。此配置只影响 wslc，不是 Docker 的资源配置。其镜像拉取曾因连接 Docker Hub 超时失败；本轮没有修改全局代理配置。

Docker 安装后，原有编辑器进程的 PATH 未刷新，首次拉取因找不到 docker-credential-desktop 失败。验证脚本只为 Docker 子进程将 CLI 所在目录加入 PATH，随后镜像拉取成功；不需要重新登录 Docker Hub 或改变凭据配置。

## 受限容器实测

探针开始时间：2026-10-30 09:01:27（Asia/Shanghai）。脚本位于 `scripts/environment/verify_container.py`，只执行本项目编写的诊断代码，不执行目标仓库代码。先拉取官方 Python 镜像，再使用其解析出的摘要启动探针：

`python@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb`

| 检查 | 实际结果 |
| --- | --- |
| 非 root | UID 65534 |
| 源码夹具与根文件系统 | 写入均返回 EROFS；只挂载临时专用夹具 |
| 网络 | 只有 lo 接口，外部连接失败 |
| capabilities | CapEff 与 CapBnd 均为 0 |
| 禁止提权 / seccomp | NoNewPrivs=1，Seccomp=2 |
| CPU / 内存 / PID | cgroup 实际值为 1 CPU、268435456 字节、64 个进程；不是仅记录启动参数 |
| 宿主文件与 socket | 无 /mnt/c、/mnt/d 或 /var/run/docker.sock；不挂载宿主 HOME、项目根或证据目录 |
| 凭据环境变量 | DEEPSEEK_API_KEY、OPENAI_API_KEY、GITHUB_TOKEN 未传入 |
| 清理 | 探针容器已删除，按本次名称前缀查询无残留 |

复查命令：

```powershell
$dockerPath = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
.venv\Scripts\python scripts/environment/verify_container.py --docker $dockerPath --context desktop-linux
```

该脚本会拉取镜像、创建和删除自己的具名容器；不会 prune、删除其他容器或清空镜像。运行记录会覆盖指定输出文件，当前输出仅用于环境小实验，不是正式 Run 的不可覆盖证据存储。

原始记录保留于忽略目录 `.repopilot/environment/`：docker-provision-result.json、docker-start-result.json、container-verification.json、安装和下载诊断日志。公共提交只保留脚本和本文件中的核验摘要。

仓库验证：`ruff check .` 与 `ruff format --check .` 通过（51 个 Python 文件）；18 份规划文档的 UTF-8 和 68 个相对链接检查通过；`git diff --check` 通过。产品源码和测试未修改，本轮没有重复运行产品测试套件，环境验证以实际容器探针为依据。

## 实现边界

环境准备已完成，P1-01 的 Linux 容器小实验通过。此前的底座合成接口实验与本次容器探针分别通过，尚未组成生产引擎集成。M2 的 SandboxRunner、超时及输出预算、工作区导入导出、Oracle 和可信证据登记仍未实现。

产品 `target_execution_enabled` 继续为 false；不能因 Docker 可用而直接执行第三方项目。其余项目实现保持暂停。本次未新增模型调用、目标项目运行或修复结果。

依据：[Microsoft WSL 容器说明](https://learn.microsoft.com/en-us/windows/wsl/wsl-container)、[wslc 配置](https://learn.microsoft.com/en-us/windows/wsl/wsl-container-settings)、[WSL 宿主集成配置](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)、[Docker Windows 安装说明](https://docs.docker.com/desktop/setup/install/windows-install/)。关于本机选项支持和约束生效的结论来自实际命令与探针。
