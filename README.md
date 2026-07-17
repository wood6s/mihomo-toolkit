# mihomo-toolkit

把一台 Debian 主机上的 Mihomo 服务、Zsh 代理命令、交互式节点选择和安全订阅管理整理成可复用项目。

仓库来自一套实际运行的本机配置，但**不包含**节点服务器、UUID、密码、订阅 URL、provider 缓存或完整的个人路由规则。项目即使是私有仓库，也只提交可公开审查的模板。

## 功能

- 以独立的 `mihomo` 系统用户运行服务，并应用 systemd 加固。
- `proxy_on` / `proxy_off` 只影响当前终端的代理环境变量。
- 多终端引用登记和异常退出清理，避免重复启动或遗留计数。
- `proxy_select` 通过本地 Controller API 选择订阅和节点。
- `proxy_add` / `proxy_remove` 隐藏读取 HTTPS 订阅 URL，修改前验证配置，失败自动回滚。
- 安装器保留已有 `/etc/mihomo/config.yaml`，不会覆盖真实配置。

## 前置条件

项目面向 Debian/Ubuntu 类 systemd 主机，要求：

- Mihomo 已安装为 `/usr/local/bin/mihomo`；
- `zsh`、`curl`、`jq`、`util-linux`（提供 `flock`）；
- Python 3 和 PyYAML；
- 当前用户具有 sudo 权限。

Debian 可安装脚本依赖：

```bash
sudo apt install zsh curl jq util-linux python3 python3-yaml
```

## 安装

```bash
git clone https://github.com/wood6s/mihomo-toolkit.git
cd mihomo-toolkit
sudo ./scripts/install.sh
```

安装器会：

1. 创建 `mihomo` 系统用户（若不存在）；
2. 在没有现有配置时安装 `config/config.example.yaml`；
3. 安装 systemd 单元、订阅管理器和用户侧命令；
4. 为当前 sudo 用户添加仅允许启动 `mihomo.service` 的免密规则；
5. 在 `~/.zshrc` 中加入带标记、可重复执行的 source 区块；
6. 测试配置并启用服务。

如通过 root 登录执行，请明确指定目标用户：

```bash
sudo MIHOMO_INSTALL_USER=alice ./scripts/install.sh
```

新安装使用的是无真实出口的示例节点。请替换 `/etc/mihomo/config.yaml` 中的示例，或在进入 Zsh 后运行 `proxy_add` 添加 HTTPS 订阅。

## 代理命令

重新进入 Zsh，或执行：

```zsh
source ~/.config/mihomo-control.zsh
```

可用命令：

| 命令 | 作用 |
| --- | --- |
| `proxy_on` | 启动服务并为当前终端设置 HTTP/HTTPS/SOCKS 代理 |
| `proxy_off` | 清除当前终端的代理变量并释放登记 |
| `proxy_select` | 交互选择订阅与节点 |
| `proxy_add` | 隐藏输入并添加 HTTPS 订阅 |
| `proxy_remove` | 删除由工具管理的订阅 |
| `proxy_list` | 只列订阅名称，不显示 URL |
| `proxy_status` | 显示服务、终端登记和当前节点状态 |
| `proxy_users` | 列出已登记的终端进程 |
| `proxy_gc` | 清理异常退出留下的登记 |
| `proxy_help` | 显示简短帮助 |

默认参数可在 `~/.config/mihomo-toolkit/env.zsh` 中覆盖。安装器首次运行时会从 [`config/env.zsh.example`](config/env.zsh.example) 创建该文件。尚未添加受管订阅时，选择命令会自动回退到示例配置中的 `默认代理`；首次 `proxy_add` 后使用总入口 `代理选择`。

## 订阅管理的安全边界

`proxy_add` 先完成 sudo 验证，再通过隐藏输入读取 URL，并经标准输入交给 root 管理器。管理器只接受 HTTPS、不接受 `user:password@host`，在写入前会：

- 对配置加独占锁；
- 只维护带明确起止标记的区块；
- 运行 `mihomo -t`；
- 创建权限为 `0600` 的时间戳备份；
- 原子替换配置并重启服务；
- 重启失败时恢复配置和状态。

订阅 URL 最终存在 root 管理的 Mihomo 配置、状态与备份中，因此这些文件仍须视为密钥材料。详见 [`docs/security.md`](docs/security.md)。

## 验证

```bash
make check
```

检查包括 Bash/Zsh/Python 语法、订阅管理器单元测试、示例 YAML 解析和敏感信息启发式扫描。如果本机已安装 ShellCheck，`make check` 会自动运行它。

## 项目结构

```text
bin/                         用户侧可执行命令
config/                      脱敏配置与环境示例
docs/                        安全说明和本机快照摘要
sbin/                        root 订阅管理器
shell/                       Zsh proxy_* 函数
systemd/                     服务单元与加固覆盖
scripts/                     安装和卸载脚本
tests/                       静态检查与单元测试
```

## 卸载

```bash
sudo ./scripts/uninstall.sh
```

卸载器不会删除 `/etc/mihomo`、Mihomo 二进制、订阅状态、备份或用户环境文件，避免误删凭据和手工配置。
