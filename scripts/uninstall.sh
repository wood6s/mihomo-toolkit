#!/usr/bin/env bash
set -euo pipefail

TARGET_USER="${MIHOMO_INSTALL_USER:-${SUDO_USER:-}}"

die() {
    echo "错误：$*" >&2
    exit 1
}

[[ "$EUID" -eq 0 ]] || die "请通过 sudo 运行卸载器。"
[[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] || \
    die "无法确定目标用户，请设置 MIHOMO_INSTALL_USER。"
getent passwd "$TARGET_USER" >/dev/null || die "用户不存在：$TARGET_USER"

TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
systemctl disable --now mihomo.service 2>/dev/null || true

rm -f -- \
    /etc/systemd/system/mihomo.service.d/hardening.conf \
    /etc/systemd/system/mihomo.service \
    "/etc/sudoers.d/mihomo-toolkit-$TARGET_USER" \
    /usr/local/sbin/mihomo-subscription-manager \
    "$TARGET_HOME/.local/bin/mihomo-ref" \
    "$TARGET_HOME/.local/bin/mihomo-select" \
    "$TARGET_HOME/.config/mihomo-control.zsh"
rmdir /etc/systemd/system/mihomo.service.d 2>/dev/null || true
systemctl daemon-reload

ZSHRC="$TARGET_HOME/.zshrc"
if [[ -L "$ZSHRC" ]]; then
    echo "警告：$ZSHRC 是符号链接，未自动移除 source 区块。" >&2
elif [[ -f "$ZSHRC" ]] && grep -Fq '# BEGIN MIHOMO TOOLKIT' "$ZSHRC"; then
    runuser -u "$TARGET_USER" -- sed -i \
        '/^# BEGIN MIHOMO TOOLKIT$/,/^# END MIHOMO TOOLKIT$/d' \
        "$ZSHRC"
fi

echo "工具已卸载。以下敏感或手工管理的数据已保留："
echo "  /etc/mihomo"
echo "  /usr/local/bin/mihomo"
echo "  $TARGET_HOME/.config/mihomo-toolkit/env.zsh"
