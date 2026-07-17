typeset _mihomo_env_file="${XDG_CONFIG_HOME:-$HOME/.config}/mihomo-toolkit/env.zsh"
[[ -r "$_mihomo_env_file" ]] && source "$_mihomo_env_file"
unset _mihomo_env_file

# 重复 source 时保留当前终端已经登记的代理状态。
typeset -g _MIHOMO_PROXY_ACTIVE="${_MIHOMO_PROXY_ACTIVE:-0}"
typeset -g _MIHOMO_PROXY_CLEANING="${_MIHOMO_PROXY_CLEANING:-0}"

# 可在 source 本文件前覆盖这些值。
typeset -g MIHOMO_HTTP_PROXY="${MIHOMO_HTTP_PROXY:-http://127.0.0.1:7890}"
typeset -g MIHOMO_SOCKS_PROXY="${MIHOMO_SOCKS_PROXY:-socks5h://127.0.0.1:7890}"
typeset -g MIHOMO_API="${MIHOMO_API:-http://127.0.0.1:9090}"
typeset -g MIHOMO_ENTRY_GROUP="${MIHOMO_ENTRY_GROUP:-代理选择}"
typeset -g MIHOMO_BASE_GROUP="${MIHOMO_BASE_GROUP:-默认代理}"
typeset -g MIHOMO_SERVICE="${MIHOMO_SERVICE:-mihomo.service}"
typeset -g MIHOMO_REF="${MIHOMO_REF:-$HOME/.local/bin/mihomo-ref}"
typeset -g MIHOMO_SELECT="${MIHOMO_SELECT:-$HOME/.local/bin/mihomo-select}"
typeset -g MIHOMO_MANAGER="${MIHOMO_MANAGER:-/usr/local/sbin/mihomo-subscription-manager}"

_mihomo_clear_environment() {
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
    unset http_proxy https_proxy all_proxy
    unset NO_PROXY no_proxy
}

_mihomo_proxy_exit_cleanup() {
    (( _MIHOMO_PROXY_ACTIVE == 1 )) || return 0
    (( _MIHOMO_PROXY_CLEANING == 0 )) || return 0

    typeset -g _MIHOMO_PROXY_CLEANING=1

    "$MIHOMO_REF" \
        release "${ZSH_PID:-$$}" \
        >/dev/null 2>&1 || true

    _mihomo_clear_environment

    typeset -g _MIHOMO_PROXY_ACTIVE=0
    typeset -g _MIHOMO_PROXY_CLEANING=0
}

proxy_on() {
    local shell_pid="${ZSH_PID:-$$}"
    local user_count

    if (( _MIHOMO_PROXY_ACTIVE == 1 )); then
        echo "当前终端已经开启代理。"
        proxy_status
        return 0
    fi

    user_count="$(
        "$MIHOMO_REF" acquire "$shell_pid"
    )" || {
        echo "启动或登记 Mihomo 代理失败。"
        return 1
    }

    export HTTP_PROXY="$MIHOMO_HTTP_PROXY"
    export HTTPS_PROXY="$MIHOMO_HTTP_PROXY"
    export ALL_PROXY="$MIHOMO_SOCKS_PROXY"

    export http_proxy="$HTTP_PROXY"
    export https_proxy="$HTTPS_PROXY"
    export all_proxy="$ALL_PROXY"

    export NO_PROXY="localhost,127.0.0.1,::1"
    export no_proxy="$NO_PROXY"

    typeset -g _MIHOMO_PROXY_ACTIVE=1

    echo "当前终端代理已开启。"
    echo "使用代理的终端数：$user_count"
    echo "Mihomo 服务：$(systemctl is-active "$MIHOMO_SERVICE")"
}

proxy_off() {
    local shell_pid="${ZSH_PID:-$$}"
    local user_count

    _mihomo_clear_environment

    if (( _MIHOMO_PROXY_ACTIVE == 0 )); then
        # 顺便清理其他意外退出终端留下的记录
        user_count="$(
            "$MIHOMO_REF" gc
        )" || return 1

        echo "当前终端代理未开启。"
        echo "登记使用的终端数：$user_count"
        return 0
    fi

    user_count="$(
        "$MIHOMO_REF" release "$shell_pid"
    )" || {
        echo "代理变量已清除，但释放登记失败。"
        return 1
    }

    typeset -g _MIHOMO_PROXY_ACTIVE=0

    echo "当前终端代理已关闭。"

    if [[ "$user_count" == "0" ]]; then
        echo "没有其他终端使用代理，Mihomo 服务保持运行。"
    else
        echo "仍有 $user_count 个终端使用代理，Mihomo 保持运行。"
    fi
}

proxy_select() {
    MIHOMO_API="$MIHOMO_API" \
        MIHOMO_ENTRY_GROUP="$MIHOMO_ENTRY_GROUP" \
        MIHOMO_BASE_GROUP="$MIHOMO_BASE_GROUP" \
        MIHOMO_SERVICE="$MIHOMO_SERVICE" \
        "$MIHOMO_SELECT"
}

proxy_gc() {
    local user_count

    user_count="$(
        "$MIHOMO_REF" gc
    )" || return 1

    echo "已清理失效终端记录。"
    echo "仍在使用代理的终端数：$user_count"
    echo "Mihomo 服务：$(systemctl is-active "$MIHOMO_SERVICE" 2>/dev/null || true)"
}

proxy_users() {
    "$MIHOMO_REF" list
}

_mihomo_show_selection() {
    local api="$MIHOMO_API"
    local entry_group="$MIHOMO_ENTRY_GROUP"
    local entry_uri entry_json current_subscription target_uri target_json next_target
    local current_node
    local -a selection_path
    local -i depth

    command -v curl >/dev/null 2>&1 || return 0
    command -v jq >/dev/null 2>&1 || return 0

    entry_uri="$(jq -nr --arg value "$entry_group" '$value | @uri')"
    entry_json="$(curl -fsS "$api/proxies/$entry_uri" 2>/dev/null)" || {
        entry_group="$MIHOMO_BASE_GROUP"
        entry_uri="$(jq -nr --arg value "$entry_group" '$value | @uri')"
        entry_json="$(curl -fsS "$api/proxies/$entry_uri" 2>/dev/null)" || {
            echo "当前订阅：无法读取"
            echo "当前节点：无法读取"
            return 0
        }
    }

    current_subscription="$(jq -r '.now // "未知"' <<<"$entry_json")"
    echo "当前订阅：$current_subscription"

    current_node="$current_subscription"
    selection_path=("$current_subscription")
    for (( depth = 0; depth < 8; depth++ )); do
        target_uri="$(jq -nr --arg value "$current_node" '$value | @uri')"
        target_json="$(curl -fsS "$api/proxies/$target_uri" 2>/dev/null)" || break
        next_target="$(jq -r '.now // empty' <<<"$target_json")"
        [[ -n "$next_target" && "$next_target" != "$current_node" ]] || break
        current_node="$next_target"
        selection_path+=("$current_node")
    done

    echo "当前节点：$current_node"
    if (( ${#selection_path} > 2 )); then
        echo "选择路径：${(j: → :)selection_path}"
    fi
}

proxy_add() {
    emulate -L zsh
    local label subscription_url result
    local manager="$MIHOMO_MANAGER"

    [[ -x "$manager" ]] || {
        echo "订阅管理程序尚未安装：$manager"
        return 1
    }

    read "label?订阅显示名称："
    [[ -n "$label" ]] || {
        echo "订阅名称不能为空。"
        return 1
    }

    # 先完成 sudo 验证，避免订阅地址在等待输入密码时停留在内存中。
    sudo -v || return 1
    read -rs "subscription_url?HTTPS 订阅地址（隐藏输入）："
    echo
    [[ -n "$subscription_url" ]] || {
        echo "订阅地址不能为空。"
        return 1
    }

    print -rn -- "$subscription_url" |
        sudo -n "$manager" add "$label"
    result=$?
    subscription_url=''
    unset subscription_url
    return $result
}

proxy_remove() {
    emulate -L zsh
    local -a subscriptions
    local selected names_output
    local manager="$MIHOMO_MANAGER"

    [[ -x "$manager" ]] || {
        echo "订阅管理程序尚未安装：$manager"
        return 1
    }
    sudo -v || return 1
    names_output="$(sudo -n "$manager" names)" || return 1
    if [[ -z "$names_output" ]]; then
        echo "当前没有由本工具管理的订阅。"
        return 0
    fi
    subscriptions=("${(@f)names_output}")

    echo "请选择要删除的订阅："
    PS3="输入订阅序号："
    select selected in "${subscriptions[@]}"; do
        [[ -n "$selected" ]] && break
        echo "序号无效，请重新输入。"
    done

    read "REPLY?确认删除“$selected”？输入 YES："
    [[ "$REPLY" == "YES" ]] || {
        echo "已取消。"
        return 0
    }
    sudo -n "$manager" remove "$selected"
}

proxy_list() {
    local manager="$MIHOMO_MANAGER"
    [[ -x "$manager" ]] || {
        echo "订阅管理程序尚未安装：$manager"
        return 1
    }
    sudo "$manager" list
}

proxy_status() {
    local user_count
    local service_state

    user_count="$(
        "$MIHOMO_REF" status 2>/dev/null
    )" || user_count="未知"

    service_state="$(systemctl is-active "$MIHOMO_SERVICE" 2>/dev/null || true)"
    echo "Mihomo 服务：$service_state"
    echo "登记使用的终端数：$user_count"

    if [[ "$service_state" == "active" ]]; then
        _mihomo_show_selection
    fi

    if (( _MIHOMO_PROXY_ACTIVE == 1 )); then
        echo "当前终端代理：已开启"
        echo "HTTPS_PROXY=${HTTPS_PROXY:-未设置}"
    else
        echo "当前终端代理：未开启"
    fi
}

# zsh 正常退出、关闭终端或 SSH 会话结束时自动释放
autoload -Uz add-zsh-hook
add-zsh-hook -d zshexit _mihomo_proxy_exit_cleanup 2>/dev/null || true
add-zsh-hook zshexit _mihomo_proxy_exit_cleanup
proxy_help() {
    cat <<'HELP'
proxy_on      为当前终端开启代理，必要时启动 Mihomo
proxy_off     关闭当前终端代理，不停止常驻的 Mihomo 服务
proxy_select  选择 Mihomo 策略组和代理节点
proxy_add     隐藏输入并添加 HTTPS 订阅
proxy_remove  交互选择并删除已添加的订阅
proxy_list    列出已添加的订阅（不显示地址）
proxy_status  查看服务状态、使用终端数和当前终端代理状态
proxy_users   列出当前登记使用代理的终端进程
proxy_gc      清理异常退出终端留下的记录
proxy_help    显示本帮助信息
HELP
}
