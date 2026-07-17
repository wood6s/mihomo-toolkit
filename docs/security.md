# 安全说明

## 不进入 Git 的内容

- 真实 `/etc/mihomo/config.yaml`；
- 订阅 URL 和 `.managed-subscriptions.json`；
- `proxy_providers/` 下载缓存；
- `subscription-backups/`；
- 节点服务器、UUID、密码、密钥和传输参数。

`.gitignore` 是最后一道防误操作措施，不应代替提交前检查。`make check` 会扫描常见代理 URI、本机绝对路径和备份文件名，但启发式扫描无法证明没有秘密。

提交前建议再运行专用工具，例如 Gitleaks，并检查：

```bash
git diff --cached
git status --short
```

## 本地 Controller

模板将 Controller 固定在 loopback，且代理端口默认不开放到 LAN，因此未配置 Controller secret。如果改变监听地址，必须为 Controller 设置强 secret，并限制防火墙来源。

## 订阅存储

订阅管理器会把 URL 写入 `/etc/mihomo/config.yaml` 和 root-only 状态文件，并把旧版本保存到 root-only 备份目录。系统备份、诊断包和日志收集同样必须排除这些路径。

## sudo 权限

安装器只为目标用户授予以下免密命令：

```text
/usr/bin/systemctl start mihomo.service
```

订阅增删仍要求普通 sudo 验证。URL 使用隐藏输入，并通过标准输入传给管理器，避免出现在参数列表和 shell 历史中。
