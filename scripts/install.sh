#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="${MIHOMO_INSTALL_USER:-${SUDO_USER:-}}"

die() {
    echo "错误：$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"
}

[[ "$EUID" -eq 0 ]] || die "请通过 sudo 运行安装器。"
[[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] || \
    die "无法确定目标用户，请设置 MIHOMO_INSTALL_USER。"
getent passwd "$TARGET_USER" >/dev/null || die "用户不存在：$TARGET_USER"

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -d "$TARGET_HOME" ]] || die "目标用户主目录不存在：$TARGET_HOME"

for command_name in curl flock getent install jq python3 runuser systemctl visudo zsh; do
    require_command "$command_name"
done
[[ -x /usr/local/bin/mihomo ]] || die "找不到 /usr/local/bin/mihomo"
python3 -c 'import yaml' >/dev/null 2>&1 || die "缺少 PyYAML（Debian 包：python3-yaml）"

if ! getent group mihomo >/dev/null; then
    groupadd --system mihomo
fi
if ! id -u mihomo >/dev/null 2>&1; then
    useradd \
        --system \
        --gid mihomo \
        --home-dir /etc/mihomo \
        --no-create-home \
        --shell /usr/sbin/nologin \
        mihomo
fi

if [[ ! -d /etc/mihomo ]]; then
    install -d -m 0700 -o mihomo -g mihomo /etc/mihomo
fi
if [[ ! -e /etc/mihomo/config.yaml ]]; then
    install -m 0600 -o mihomo -g mihomo \
        "$REPO_ROOT/config/config.example.yaml" \
        /etc/mihomo/config.yaml
    echo "已安装无真实出口的示例配置。"
else
    runuser -u mihomo -- test -r /etc/mihomo/config.yaml || \
        die "现有配置无法由 mihomo 用户读取；请先检查所有权和权限。"
    echo "保留现有配置：/etc/mihomo/config.yaml"
fi
runuser -u mihomo -- test -x /etc/mihomo || \
    die "mihomo 用户无法进入 /etc/mihomo；请先检查目录权限。"
runuser -u mihomo -- test -w /etc/mihomo || \
    die "mihomo 用户无法写入 /etc/mihomo；provider 和缓存将无法更新。"

install -D -m 0644 "$REPO_ROOT/systemd/mihomo.service" \
    /etc/systemd/system/mihomo.service
install -D -m 0644 "$REPO_ROOT/systemd/mihomo.service.d/hardening.conf" \
    /etc/systemd/system/mihomo.service.d/hardening.conf
install -m 0755 "$REPO_ROOT/sbin/mihomo-subscription-manager" \
    /usr/local/sbin/mihomo-subscription-manager

runuser -u "$TARGET_USER" -- mkdir -p \
    "$TARGET_HOME/.local/bin" \
    "$TARGET_HOME/.config/mihomo-toolkit"

runuser -u "$TARGET_USER" -- install -m 0755 \
    "$REPO_ROOT/bin/mihomo-ref" "$TARGET_HOME/.local/bin/mihomo-ref"
runuser -u "$TARGET_USER" -- install -m 0755 \
    "$REPO_ROOT/bin/mihomo-select" "$TARGET_HOME/.local/bin/mihomo-select"
runuser -u "$TARGET_USER" -- install -m 0600 \
    "$REPO_ROOT/shell/mihomo-control.zsh" "$TARGET_HOME/.config/mihomo-control.zsh"
if [[ ! -e "$TARGET_HOME/.config/mihomo-toolkit/env.zsh" ]]; then
    runuser -u "$TARGET_USER" -- install -m 0600 \
        "$REPO_ROOT/config/env.zsh.example" \
        "$TARGET_HOME/.config/mihomo-toolkit/env.zsh"
fi

ZSHRC="$TARGET_HOME/.zshrc"
if ! runuser -u "$TARGET_USER" -- grep -Fq '# BEGIN MIHOMO TOOLKIT' "$ZSHRC" \
    2>/dev/null; then
    runuser -u "$TARGET_USER" -- tee -a "$ZSHRC" >/dev/null <<'ZSHRC_BLOCK'

# BEGIN MIHOMO TOOLKIT
source "$HOME/.config/mihomo-control.zsh"
# END MIHOMO TOOLKIT
ZSHRC_BLOCK
fi

SUDOERS_FILE="/etc/sudoers.d/mihomo-toolkit-$TARGET_USER"
SUDOERS_TEMP="$(mktemp)"
trap 'rm -f -- "$SUDOERS_TEMP"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start mihomo.service\n' \
    "$TARGET_USER" > "$SUDOERS_TEMP"
chmod 0600 "$SUDOERS_TEMP"
visudo -cf "$SUDOERS_TEMP" >/dev/null
install -m 0440 "$SUDOERS_TEMP" "$SUDOERS_FILE"

runuser -u mihomo -- /usr/local/bin/mihomo -t -d /etc/mihomo
systemctl daemon-reload
systemctl enable --now mihomo.service

echo
echo "安装完成。重新进入 Zsh，或运行："
echo "  source \"$TARGET_HOME/.config/mihomo-control.zsh\""
echo "随后可运行：proxy_help"
