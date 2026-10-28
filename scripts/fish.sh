#!/bin/sh
# Look at her on the always-on box from your laptop, every time shown in your timezone
# (TZ= in this checkout's .env; the box's own clock may be elsewhere). See docs/box_zh.md.
#
#   scripts/fish.sh show      what she remembers right now
#   scripts/fish.sh notebook  last night's exported notebook (diary, notes, phase)
#   scripts/fish.sh logs      live WeChat log (Ctrl-C to stop)
#   scripts/fish.sh sent      the last 20 messages she sent, with message_id
#   scripts/fish.sh timers    when the nightly routine runs next
#   scripts/fish.sh browse    make her browse now (by hand; on her own she browses only when she likes)
set -eu
BOX="${BOX:-ubuntu-tailscale}"
cd "$(dirname "$0")/.."
TZ_USER="$(sed -n 's/^TZ=//p' .env 2>/dev/null | tail -1)"
TZ_USER="${TZ_USER:-UTC}"
case "${1:-show}" in
    show)     ssh "$BOX" "cd Dafeiyu && TZ=$TZ_USER .venv/bin/python -m fish show" ;;
    notebook) ssh "$BOX" "cat Dafeiyu/data/notebook_export.md" ;;
    logs)     ssh -t "$BOX" "TZ=$TZ_USER journalctl --user -u dafeiyu-wechat -f -o short-iso" ;;
    sent)     ssh "$BOX" "TZ=$TZ_USER journalctl --user -u dafeiyu-wechat -o short-iso --no-pager | grep '→' | tail -20" ;;
    timers)   ssh "$BOX" "TZ=$TZ_USER systemctl --user list-timers --no-pager | grep -E 'NEXT|dafeiyu'" ;;
    browse)   ssh "$BOX" "cd Dafeiyu && TZ=$TZ_USER .venv/bin/python -m fish browse" ;;
    *) echo "usage: scripts/fish.sh [show|notebook|logs|sent|timers|browse]" >&2; exit 2 ;;
esac
