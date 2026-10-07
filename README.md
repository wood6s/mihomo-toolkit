# mihomo-toolkit

本项目适用于 Debian/Ubuntu systemd 主机的 Mihomo 代理管理，支持无 GUI 服务器和 GNOME 桌面系统代理。

当前版本见 [`VERSION`](VERSION)，变更记录见 [`CHANGELOG.md`](CHANGELOG.md)。

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

GNOME 桌面集成使用 `gsettings`（`libglib2.0-bin`）、`gsettings-desktop-schemas` 和 D-Bus；没有 GNOME 时仍可持久管理终端及用户服务的代理环境。

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
6. 在 Shell/桌面登录文件中安装默认代理加载区块，升级时保留已有开关状态；
7. 测试配置并启用服务。

如通过 root 登录执行，请明确指定目标用户：

```bash
sudo MIHOMO_INSTALL_USER=alice ./scripts/install.sh
```

新安装使用的是无真实出口的示例节点。请替换 `/etc/mihomo/config.yaml` 中的示例，或在进入 Zsh 后运行 `proxy_add` 添加 HTTPS 订阅。

配置好可用节点后执行 `proxy_global_on`，即可持久开启当前用户的默认代理。安装器不会为尚无可用节点的新安装自动开启代理。

## 代理命令

重新进入 Zsh，或执行：

```zsh
source ~/.config/mihomo-control.zsh
```

可用命令：

| 命令 | 作用 |
| --- | --- |
| `proxy_global_on` | 开启当前用户的系统代理、新终端及用户服务默认代理；同时开启当前终端，重启后保留 |
| `proxy_global_off` | 关闭上述默认代理并关闭当前终端代理；重启后保留 |
| `proxy_global_status` | 查看持久开关及桌面系统代理设置 |
| `proxy_on` | 启动服务并为当前终端设置 HTTP/HTTPS/SOCKS 代理 |
| `proxy_off` | 清除当前终端的代理变量并释放登记 |
| `proxy_check [URL]` | 测试当前终端代理的 HTTPS 连通性，默认请求 gstatic 204 地址 |
| `proxy_select` | 交互选择订阅与节点，GLOBAL 同步跟随 |
| `proxy_mode [rule\|global\|direct]` | 查看或切换 Mihomo 当前运行模式 |
| `proxy_add` | 隐藏输入并添加 HTTPS 订阅 |
| `proxy_remove` | 删除由工具管理的订阅 |
| `proxy_list` | 只列订阅名称，不显示 URL |
| `proxy_status` | 显示服务、默认代理、路由模式、GLOBAL 出口、终端登记和当前节点状态 |
| `proxy_users` | 列出已登记的终端进程 |
| `proxy_gc` | 清理异常退出留下的登记 |
| `proxy_help` | 显示简短帮助 |

默认参数可在 `~/.config/mihomo-toolkit/env.zsh` 中覆盖。安装器首次运行时会从 [`config/env.zsh.example`](config/env.zsh.example) 创建该文件。尚未添加受管订阅时，选择命令会自动回退到示例配置中的 `默认代理`；首次 `proxy_add` 后使用总入口 `代理选择`。

`proxy_add` 会保留配置中已有的 `proxy-providers`，仅在同一映射内添加带管理标记的新订阅源；删除订阅也只移除工具管理的条目。原有订阅源、注释和策略组的 `use` 引用会保留。名称或缓存路径冲突、重复 YAML 字段，以及无法安全处理的外部映射别名会停止操作并给出提示，避免覆盖现有配置。

若配置重新排版导致管理标记丢失，工具会用已保存的订阅状态严格核对旧订阅源和策略组，再恢复标记。恢复过程可能规范化对应配置段的排版与注释，但会验证配置值不变，并继续经过 Mihomo 校验、备份和失败回滚；记录缺失或内容不匹配时停止操作，不根据名称前缀猜测归属。

`proxy_remove` 会列出总入口中的所有代理选项，包括 `默认代理`。移除默认入口只会把它从总入口中隐藏，不会删除用户原有的策略组或节点配置。如果移除后没有任何代理入口，总入口会回退到 Mihomo 内置的 `DIRECT`，不会重新加入已移除的默认入口。

## 默认代理与开关

```zsh
proxy_global_on       # 持久开启
proxy_global_off      # 持久关闭
proxy_on              # 仅开启当前终端
proxy_off             # 仅关闭当前终端
proxy_status
proxy_check
```

默认使用 `127.0.0.1:7890`，同时配置大小写 HTTP/HTTPS/SOCKS 代理变量；本机和内网地址保留直连。
配置覆盖当前用户的 Shell、桌面登录、systemd 用户服务，以及可用的 GNOME 系统代理。
只有支持系统代理或代理环境变量的应用会使用它。Mihomo 的分流规则保持不变，不启用 TUN。

已经运行的应用可能需要重启；其他已打开的终端执行 `proxy_on` 或 `proxy_off` 同步。
关闭代理后 Mihomo 服务继续待命。重复加载 Zsh 配置会保留当前终端单独选择的开关状态。

持久文件为 `~/.config/mihomo-toolkit/proxy-defaults.sh` 和 `~/.config/environment.d/90-mihomo-proxy.conf`。
没有活动的 systemd 用户会话时，配置会在下次登录时应用到用户服务。
其他 Shell 可执行 `~/.local/bin/mihomo-global-proxy on|off|status`，然后运行
`. ~/.config/mihomo-toolkit/proxy-defaults.sh` 更新当前终端。该可执行命令支持同名的 `MIHOMO_*` 环境变量；Zsh 包装函数会自动传入 `env.zsh` 中的配置。
查看已安装版本使用 `~/.local/bin/mihomo-global-proxy --version`。

## 路由模式

```zsh
proxy_mode           # 查看当前模式和 GLOBAL 的出口路径
proxy_mode rule      # 按规则分流
proxy_mode global    # GLOBAL 跟随 proxy_select 选择的订阅/节点
proxy_mode direct    # 所有进入 Mihomo 的流量直连
```

`proxy_global_on/off` 管理系统代理及默认环境，`proxy_mode` 管理流量进入 Mihomo 后的路由方式，两者独立。
切换为 `global` 前，工具将 `GLOBAL` 绑定到 `proxy_select` 使用的“代理选择”入口；没有该入口时回退到“默认代理”。
绑定的是选择入口，因此以后使用 `proxy_select` 更换订阅或节点，GLOBAL 会随之切换。如果你主动选了 `DIRECT`，GLOBAL 也会跟随直连。
无法建立关联时不会切换为 `global`；控制接口写入后会检查结果，失败时尝试恢复原状态并报告。

路由模式通过控制接口即时修改，不改写 `/etc/mihomo/config.yaml`。重启或重载服务后的模式以配置文件中的 `mode` 为准。
其他 Shell 可通过 `~/.local/bin/mihomo-mode [rule|global|direct]` 使用同一功能；支持 `MIHOMO_API`、`MIHOMO_ENTRY_GROUP`、`MIHOMO_BASE_GROUP` 环境变量。

## 验证

```bash
make check
```

检查包括 Bash/Zsh/Python 语法、订阅管理和默认代理的行为测试、启动配置的重复安装/移除、示例 YAML 解析和敏感信息启发式扫描。代理测试隔离用户配置，不修改本机正在使用的代理。如果本机已安装 ShellCheck，`make check` 会自动运行它；GitHub Actions 会安装 ShellCheck 并执行相同检查。

## 版本发布约定

项目所有者已授权助手自行判断升版和上传 GitHub 的时机。关键更新完成且通过相应验证后，由助手选择版本号、更新 `VERSION` 和 `CHANGELOG.md`、提交并上传 GitHub，同时发布对应版本标签和 Release，无需逐次等待单独的发布指令。仍在排障或关键兼容性未验证时继续修复，保留未发布条目；发布后报告版本、链接与验证结果。具体规则见 [`AGENTS.md`](AGENTS.md)。

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

卸载器先关闭系统代理，再移除工具生成的默认代理文件和启动区块。关闭失败时会停止卸载并保留服务，避免应用继续指向已经关闭的代理。
卸载器不会删除 `/etc/mihomo`、Mihomo 二进制、订阅状态、备份或用户手工维护的 `env.zsh`，避免误删凭据和手工配置。
