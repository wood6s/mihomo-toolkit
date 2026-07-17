#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

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
PYTHONPYCACHEPREFIX="$TEMP_DIR" python3 -m py_compile \
    sbin/mihomo-subscription-manager \
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
