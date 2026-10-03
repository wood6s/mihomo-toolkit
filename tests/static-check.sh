#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

export XDG_CONFIG_HOME="$TEMP_DIR/config"
export XDG_RUNTIME_DIR="$TEMP_DIR/runtime"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy
unset MIHOMO_HTTP_PROXY MIHOMO_SOCKS_PROXY MIHOMO_NO_PROXY MIHOMO_API MIHOMO_REF MIHOMO_MODE
mkdir -p "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"

bash -n bin/mihomo-ref
bash -n bin/mihomo-select
bash -n scripts/install.sh
bash -n scripts/uninstall.sh
zsh -n shell/mihomo-control.zsh
zsh -fc '
    source shell/mihomo-control.zsh
    typeset -g _MIHOMO_PROXY_ACTIVE=1
    typeset -g _MIHOMO_PROXY_CLEANING=1
    source shell/mihomo-control.zsh
    (( _MIHOMO_PROXY_ACTIVE == 1 && _MIHOMO_PROXY_CLEANING == 1 ))
'
inactive_check_output="$(
    zsh -fc '
        curl() {
            return 99
        }
        source shell/mihomo-control.zsh
        proxy_check
    ' 2>&1
)" && {
    echo "proxy_check 在代理未开启时意外成功。" >&2
    exit 1
}
grep -Fq '当前终端代理未开启，请先执行 proxy_on。' <<<"$inactive_check_output"

successful_check_output="$(
    zsh -fc '
        systemctl() {
            print -r -- active
        }
        curl() {
            [[ "$*" == *"--connect-timeout 5"* ]] || return 90
            [[ "$*" == *"--max-time 10"* ]] || return 91
            [[ "${argv[-1]}" == "https://www.gstatic.com/generate_204" ]] || return 92
            print -r -- "HTTP=204 remote=127.0.0.1:7890 time=0.010000s"
        }
        source shell/mihomo-control.zsh
        typeset -g _MIHOMO_PROXY_ACTIVE=1
        HTTPS_PROXY=http://127.0.0.1:7890
        proxy_check
    ' 2>&1
)"
grep -Fq 'Mihomo 服务：active' <<<"$successful_check_output"
grep -Fq '测试地址：https://www.gstatic.com/generate_204' <<<"$successful_check_output"
grep -Fq 'HTTP=204 remote=127.0.0.1:7890 time=0.010000s' <<<"$successful_check_output"
grep -Fq '代理测试：正常' <<<"$successful_check_output"

failed_check_output="$(
    zsh -fc '
        systemctl() {
            print -r -- active
        }
        curl() {
            return 28
        }
        source shell/mihomo-control.zsh
        typeset -g _MIHOMO_PROXY_ACTIVE=1
        proxy_check https://example.com/health
    ' 2>&1
)" || failed_check_status=$?
[[ "${failed_check_status:-0}" -eq 28 ]]
grep -Fq '测试地址：https://example.com/health' <<<"$failed_check_output"
grep -Fq '代理测试：失败' <<<"$failed_check_output"

unexpected_check_output="$(
    zsh -fc '
        systemctl() {
            print -r -- active
        }
        curl() {
            print -r -- "HTTP=200 remote=127.0.0.1:7890 time=0.010000s"
        }
        source shell/mihomo-control.zsh
        typeset -g _MIHOMO_PROXY_ACTIVE=1
        proxy_check https://example.com/health
    ' 2>&1
)" && {
    echo "proxy_check 在 HTTP 状态非 204 时意外成功。" >&2
    exit 1
}
grep -Fq '代理测试：异常' <<<"$unexpected_check_output"

menu_output="$(
    printf '1\nYES\n' | zsh -fc '
        sudo() {
            [[ "$1" == "-v" ]] && return 0
            [[ "$1" == "-n" ]] && shift
            case "$2" in
                names)
                    print -r -- "默认代理"
                    print -r -- "bw-month"
                    ;;
                remove)
                    print -r -- "removed:$3"
                    ;;
            esac
        }
        source shell/mihomo-control.zsh
        MIHOMO_MANAGER=/bin/true
        proxy_remove
    ' 2>&1
)"
[[ "$(grep -Fxc '1) 默认代理' <<<"$menu_output")" -eq 1 ]]
[[ "$(grep -Fxc '2) bw-month' <<<"$menu_output")" -eq 1 ]]
grep -Fq 'removed:默认代理' <<<"$menu_output"
PYTHONPYCACHEPREFIX="$TEMP_DIR" python3 -m py_compile \
    bin/mihomo-global-proxy \
    bin/mihomo-mode \
    scripts/configure-user.py \
    sbin/mihomo-subscription-manager \
    tests/test_global_proxy.py \
    tests/test_mode.py \
    tests/test_subscription_manager.py
python3 -m unittest discover -s tests -v

python3 - <<'PY'
from pathlib import Path
import yaml

path = Path("config/config.example.yaml")
data = yaml.safe_load(path.read_text(encoding="utf-8"))
assert data["allow-lan"] is False
assert data["bind-address"] == "127.0.0.1"
assert data["external-controller"] == "127.0.0.1:9090"
assert data["dns"]["fallback-filter"]["geoip"] is False
PY

if command -v shellcheck >/dev/null 2>&1; then
    shellcheck \
        bin/mihomo-ref \
        bin/mihomo-select \
        scripts/install.sh \
        scripts/uninstall.sh \
        tests/static-check.sh
fi

if rg -n '/home/[^/[:space:]]+|mihomo-config-backup-[0-9]|(ss|vmess|vless|trojan|hysteria2)://' \
    --glob '!tests/static-check.sh' .; then
    echo "检测到本机路径、备份名称或真实代理 URI。" >&2
    exit 1
fi

echo "全部检查通过。"
