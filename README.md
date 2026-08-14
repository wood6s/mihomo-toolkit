# mihomo-toolkit

本项目适用于无GUI环境的服务器代理配置，起到在纯命令行环境替代clash-verge-rev的作用。

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
| `proxy_check [URL]` | 测试当前终端代理的 HTTPS 连通性，默认请求 gstatic 204 地址 |
| `proxy_select` | 交互选择订阅与节点 |
| `proxy_add` | 隐藏输入并添加 HTTPS 订阅 |
| `proxy_remove` | 删除由工具管理的订阅 |
| `proxy_list` | 只列订阅名称，不显示 URL |
| `proxy_status` | 显示服务、终端登记和当前节点状态 |
| `proxy_users` | 列出已登记的终端进程 |
| `proxy_gc` | 清理异常退出留下的登记 |
| `proxy_help` | 显示简短帮助 |

默认参数可在 `~/.config/mihomo-toolkit/env.zsh` 中覆盖。安装器首次运行时会从 [`config/env.zsh.example`](config/env.zsh.example) 创建该文件。尚未添加受管订阅时，选择命令会自动回退到示例配置中的 `默认代理`；首次 `proxy_add` 后使用总入口 `代理选择`。

`proxy_remove` 会列出总入口中的所有代理选项，包括 `默认代理`。移除默认入口只会把它从总入口中隐藏，不会删除用户原有的策略组或节点配置。如果移除后没有任何代理入口，总入口会回退到 Mihomo 内置的 `DIRECT`，不会重新加入已移除的默认入口。

## 验证

```bash
make check
```

检查包括 Bash/Zsh/Python 语法、订阅管理器单元测试、示例 YAML 解析和敏感信息启发式扫描。如果本机已安装 ShellCheck，`make check` 会自动运行它；GitHub Actions 会安装 ShellCheck 并执行相同检查。

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
