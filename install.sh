#!/usr/bin/env bash
# 一键养一条自己的大肥鱼。Linux（systemd）和 macOS（launchd）都行。
#
#   curl -fsSL https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.sh | bash
#   ./install.sh             在已经 clone 下来的仓库里装（重复跑也安全：不覆盖已有的 .env 和记忆）
#   ./install.sh update      拉新代码、装依赖、重启她（记忆不动）
#   ./install.sh uninstall   停掉她、删掉开机自启（记忆和代码都留着）
#
# 装的东西全在一个文件夹里（默认 ~/Dafeiyu，可用 DAFEIYU_DIR 改）：代码、.venv、.env（密钥）、
# data/（她的记忆）。只在你自己的用户下注册服务，不用 sudo。
# 不想手动输入时可以预先给：DEEPSEEK_API_KEY=sk-... bash install.sh
set -euo pipefail

REPO_URL="${DAFEIYU_REPO:-https://github.com/Soda-null/whale-be-friends.git}"
UNITS=(dafeiyu-wechat.service dafeiyu-nightly.service dafeiyu-nightly.timer)
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LABELS=(com.dafeiyu.wechat com.dafeiyu.nightly)
# 决定 24 起她想逛才逛，不再每天 09:30 定时逛；老版本装过的这几个在安装 / 卸载时清掉。
RETIRED_UNITS=(dafeiyu-browse.service dafeiyu-browse.timer)
RETIRED_LABELS=(com.dafeiyu.browse)

say()  { printf '\033[1;34m🐟 %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
# Questions read from the terminal even when this script itself comes through a pipe.
has_tty() { (exec </dev/tty) 2>/dev/null; }
ask() {  # ask "问题" 默认值 -> 回答
    local reply=""
    if has_tty; then read -r -p "$1 " reply </dev/tty || true; fi
    printf '%s' "${reply:-$2}"
}
ask_secret() {
    local reply=""
    if has_tty; then read -r -s -p "$1 " reply </dev/tty || true; echo >&2; fi
    printf '%s' "$reply"
}

OS="$(uname -s)"
case "$OS" in Linux|Darwin) ;; *) die "只支持 Linux 和 macOS（Windows 请用 WSL）" ;; esac

# --- where the repo is --------------------------------------------------------------------
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$here" ] && [ -f "$here/src/fish/__main__.py" ]; then
    DIR="$here"
else
    DIR="${DAFEIYU_DIR:-$HOME/Dafeiyu}"
fi
PY="$DIR/.venv/bin/python"

find_python() {
    local c
    for c in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            command -v "$c"; return 0
        fi
    done
    return 1
}

get_code() {
    if [ -f "$DIR/src/fish/__main__.py" ]; then
        return 0
    fi
    command -v git >/dev/null 2>&1 || die "需要先装 git（Ubuntu: sudo apt install git；macOS: xcode-select --install）"
    [ -e "$DIR" ] && die "$DIR 已经存在但不是大肥鱼的仓库；换个地方：DAFEIYU_DIR=~/别的名字 bash install.sh"
    say "把代码拿到 $DIR"
    git clone -q "$REPO_URL" "$DIR"
}

install_deps() {
    if [ ! -x "$PY" ]; then
        local base
        base="$(find_python)" || die "需要 Python 3.11 或更新。Ubuntu 24.04 自带 3.12；macOS 用 brew install python@3.12"
        say "用 $base 建虚拟环境（.venv，只给她用的 Python）"
        if ! "$base" -m venv "$DIR/.venv" 2>/dev/null; then
            rm -rf "$DIR/.venv"
            die "建不了虚拟环境。Ubuntu 上先跑：sudo apt install python3-venv（或 python3.12-venv），再重跑这个脚本"
        fi
    fi
    say "装依赖（第一次要一两分钟）"
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q -r "$DIR/requirements.txt" -e "$DIR"
}

detect_tz() {
    # Where the machine actually is (its network location, the same service she uses to know
    # where she lives), not how its clock was set up: a laptop configured elsewhere keeps the
    # old timezone for years.
    local tz=""
    tz="$(curl -s --max-time 5 https://ipinfo.io/timezone 2>/dev/null || true)"
    case "$tz" in */*) printf '%s' "$tz"; return 0 ;; esac
    tz=""
    if command -v timedatectl >/dev/null 2>&1; then tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"; fi
    if [ -z "$tz" ] && [ -L /etc/localtime ]; then tz="$(readlink /etc/localtime | sed 's#.*/zoneinfo/##')"; fi
    printf '%s' "${tz:-Asia/Shanghai}"
}

env_get() { sed -n "s/^$1=//p" "$DIR/.env" 2>/dev/null | tail -1; }

write_env() {
    if [ -f "$DIR/.env" ] && [ -n "$(env_get DEEPSEEK_API_KEY)" ]; then
        say ".env 已经有了，不动它（要改就直接编辑 $DIR/.env）"
        return 0
    fi
    echo
    say "需要一个 DeepSeek 的 API key（她的脑子）。没有的话去 https://platform.deepseek.com 注册、充几块钱、建一个 key。"
    local key code tz owner
    while :; do
        key="${DEEPSEEK_API_KEY:-}"; DEEPSEEK_API_KEY=""
        [ -n "$key" ] || key="$(ask_secret '粘贴 key（输入时不显示）：')"
        [ -n "$key" ] || die "没有 key 她没法说话。拿到 key 后重跑：bash $DIR/install.sh"
        code="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $key" https://api.deepseek.com/models || true)"
        if [ "$code" = 200 ]; then say "key 能用"; break; fi
        if [ "$code" = 401 ]; then warn "DeepSeek 说这个 key 不对，再粘一次"; continue; fi
        warn "连不上 DeepSeek 检查不了（HTTP $code），先存下，之后不行再改 .env"; break
    done
    tz="$(detect_tz)"
    tz="$(ask "你在 $tz 这个时区吗（按这台机器的网络位置猜的）？她的白天黑夜按它算。回车确认，或输入别的（例如 Asia/Shanghai）：" "$tz")"
    owner="$(ask '她提到你的时候用"他"还是"她"？输入 他 或 她（回车 = 他）：' "他")"
    [ "$owner" = "她" ] || owner="他"
    umask 077
    cat > "$DIR/.env" <<EOF
# 大肥鱼的设置。密钥只存在这台电脑上，不进 git。改完重启她：bash install.sh update
DEEPSEEK_API_KEY=$key
# 你住的时区：她的"深夜""早上"按它算
TZ=$tz
# 她称呼你用 他 还是 她
FISH_OWNER=$owner
# 她能不能先找你（1 = 能，0 = 不能），一天最多几次
FISH_REACH_OUT=1
FISH_REACH_MAX=2
# 她住哪：默认是这台电脑网络所在的城市。放在云服务器上的话，填你想让她住的地方的"纬度,经度"
# （只精确到约一公里，不会记门牌）。例：FISH_HOME=31.23,121.47
# FISH_HOME=
EOF
    umask 022
    say "设置写进了 $DIR/.env"
}

wechat_login() {
    if [ -f "$DIR/data/wechat.json" ]; then
        say "微信已经绑过了（要换号：cd $DIR && ./fish wechat login）"
        return 0
    fi
    echo
    if ! has_tty; then
        say "没有终端可以显示二维码，先不绑。之后：cd $DIR && .venv/bin/python -m fish wechat login"
        return 0
    fi
    local yes
    yes="$(ask '现在绑微信吗？会出一个二维码，用你自己的微信扫（她只回扫码的这个号）。[Y/n]' Y)"
    case "$yes" in n|N|no|NO) say "先不绑。之后想绑：cd $DIR && .venv/bin/python -m fish wechat login"; return 0 ;; esac
    (cd "$DIR" && "$PY" -m fish wechat login </dev/tty) || warn "这次没绑上，之后再试：cd $DIR && .venv/bin/python -m fish wechat login"
}

# --- running her in the background --------------------------------------------------------
systemd_ok() { command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; }

install_systemd() {
    local unit_dir="$HOME/.config/systemd/user" tz u
    tz="$(env_get TZ)"; tz="${tz:-$(detect_tz)}"
    mkdir -p "$unit_dir"
    for u in "${RETIRED_UNITS[@]}"; do
        systemctl --user disable --now "$u" 2>/dev/null || true
        rm -rf "$unit_dir/$u" "$unit_dir/$u.d"
    done
    for u in "${UNITS[@]}"; do
        # The templates say %h/Dafeiyu; point them at wherever this checkout really is.
        sed "s#%h/Dafeiyu#$DIR#g" "$DIR/scripts/systemd/$u" > "$unit_dir/$u"
        mkdir -p "$unit_dir/$u.d"
    done
    for u in dafeiyu-wechat.service dafeiyu-nightly.service; do
        printf '[Service]\nEnvironment=TZ=%s\n' "$tz" > "$unit_dir/$u.d/tz.conf"
    done
    # A timer counts in the machine's timezone; re-state it in hers.
    printf '[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:30:00 %s\n' "$tz" > "$unit_dir/dafeiyu-nightly.timer.d/tz.conf"
    systemctl --user daemon-reload
    systemctl --user enable --now dafeiyu-nightly.timer >/dev/null
    if [ -f "$DIR/data/wechat.json" ]; then
        systemctl --user enable dafeiyu-wechat.service >/dev/null 2>&1
        systemctl --user restart dafeiyu-wechat.service
    fi
    # Keep her running after you log out (and after a reboot, before anyone logs in).
    if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]; then
        loginctl enable-linger "$USER" 2>/dev/null \
            || warn "退出登录后她会停。想让她一直在，跑一次：sudo loginctl enable-linger $USER"
    fi
}

plist() {  # plist label "args..." extra-xml
    local label="$1" cmd="$2" extra="$3" a args=""
    for a in $cmd; do args="$args<string>$a</string>"; done
    cat > "$LAUNCH_DIR/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>fish</string>$args</array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StandardOutPath</key><string>$DIR/data/logs/${label#com.dafeiyu.}.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/logs/${label#com.dafeiyu.}.log</string>
  $extra
</dict></plist>
EOF
}

install_launchd() {
    mkdir -p "$LAUNCH_DIR" "$DIR/data/logs"
    plist com.dafeiyu.nightly nightly '<key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>'
    plist com.dafeiyu.wechat wechat '<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>10</integer>'
    local l
    for l in "${RETIRED_LABELS[@]}"; do
        launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
        rm -f "$LAUNCH_DIR/$l.plist"
    done
    for l in "${LABELS[@]}"; do
        launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
        if [ "$l" = com.dafeiyu.wechat ] && [ ! -f "$DIR/data/wechat.json" ]; then continue; fi
        launchctl bootstrap "gui/$(id -u)" "$LAUNCH_DIR/$l.plist"
    done
    warn "Mac 合盖或睡着时她就不回了。想让她一直在，最好放在一台一直开着的 Linux 机器上。"
}

install_services() {
    if [ -n "${DAFEIYU_SKIP_SERVICES:-}" ]; then
        say "跳过开机自启（DAFEIYU_SKIP_SERVICES）"
    elif [ "$OS" = Darwin ]; then
        install_launchd
    elif systemd_ok; then
        install_systemd
    else
        warn "这台机器没有可用的 systemd（比如 WSL 没开 systemd）。手动让她跑：cd $DIR && .venv/bin/python -m fish wechat（放在 tmux 里）"
    fi
}

uninstall_services() {
    if [ -n "${DAFEIYU_SKIP_SERVICES:-}" ]; then
        say "跳过开机自启（DAFEIYU_SKIP_SERVICES）"
    elif [ "$OS" = Darwin ]; then
        local l
        for l in "${LABELS[@]}" "${RETIRED_LABELS[@]}"; do
            launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
            rm -f "$LAUNCH_DIR/$l.plist"
        done
    elif systemd_ok; then
        systemctl --user disable --now dafeiyu-wechat.service dafeiyu-nightly.timer dafeiyu-browse.timer 2>/dev/null || true
        local u
        for u in "${UNITS[@]}" "${RETIRED_UNITS[@]}"; do rm -rf "$HOME/.config/systemd/user/$u" "$HOME/.config/systemd/user/$u.d"; done
        systemctl --user daemon-reload
    fi
}

check() {
    say "跑一遍自检（不联网、不花钱）"
    (cd "$DIR" && "$PY" -m pytest -q 2>&1 | tail -1)
}

finish() {
    echo
    say "好了。她住在 $DIR"
    if [ -f "$DIR/data/wechat.json" ]; then
        echo "   去微信给她发一句话吧。第一次她会有点认生，聊多了就熟了。"
    else
        echo "   在终端里和她聊：cd $DIR && ./fish"
    fi
    cat <<EOF
   看她今天怎么样：cd $DIR && ./fish life
   看她记了什么：  cd $DIR && ./fish show
   更新 / 重启：   bash $DIR/install.sh update
   停掉她：        bash $DIR/install.sh uninstall   （记忆留在 $DIR/data/）
EOF
    if [ "$OS" = Linux ] && systemd_ok; then
        echo "   看她的实时日志：journalctl --user -u dafeiyu-wechat -f"
    elif [ "$OS" = Darwin ]; then
        echo "   看她的实时日志：tail -f $DIR/data/logs/wechat.log"
    fi
}

case "${1:-install}" in
    install)
        get_code
        install_deps
        write_env
        check
        wechat_login
        install_services
        finish
        ;;
    update)
        [ -f "$DIR/src/fish/__main__.py" ] || die "在 $DIR 没找到她；先装：bash install.sh"
        if git -C "$DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
            say "拉新代码"
            git -C "$DIR" pull -q --ff-only
        fi
        install_deps
        check
        install_services
        say "更新好了"
        ;;
    uninstall)
        uninstall_services
        say "她停了，开机也不会再起来。记忆还在 $DIR/data/；想彻底删掉就删整个 $DIR 文件夹。"
        ;;
    *) die "用法：install.sh [install|update|uninstall]" ;;
esac
