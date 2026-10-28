#!/bin/sh
# Put her on the always-on Ubuntu box (docs/box_zh.md). Run from the Mac, repo root.
#
#   scripts/deploy_box.sh              push code, install deps, (re)install service files
#   scripts/deploy_box.sh --with-data  ALSO copy .env and data/ (only when moving her there:
#                                      it overwrites the box's memory with the Mac's)
#   scripts/deploy_box.sh --start      ALSO enable linger, start the WeChat service and timer
#   scripts/deploy_box.sh --restart    ALSO restart the WeChat service (after a code change)
#
# Needs: an SSH alias for the box (BOX= in .env, default `box`); the git remote `box` is added here.
set -eu
cd "$(dirname "$0")/.."
BOX="${BOX:-$(sed -n 's/^BOX=//p' .env 2>/dev/null | tail -1)}"
BOX="${BOX:-box}"
REMOTE_DIR="Dafeiyu"
WITH_DATA=0; START=0; RESTART=0
for arg in "$@"; do
    case "$arg" in
        --with-data) WITH_DATA=1 ;;
        --start) START=1 ;;
        --restart) RESTART=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ -n "$(git status --porcelain)" ]; then
    echo "working tree is dirty; commit first (the box gets what is committed)" >&2
    exit 1
fi
if ! .venv/bin/python -m pytest -q >/dev/null 2>&1; then
    echo "tests fail here; not deploying (run .venv/bin/python -m pytest -q)" >&2
    exit 1
fi

# 1. The box receives pushes straight into its checkout (same trick as the Yaqi repo).
ssh "$BOX" "mkdir -p ~/$REMOTE_DIR && cd ~/$REMOTE_DIR && { git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git init -q -b main; } && git config receive.denyCurrentBranch updateInstead"
git remote get-url box >/dev/null 2>&1 || git remote add box "$BOX:$REMOTE_DIR"
git push -q box main
echo "pushed $(git rev-parse --short HEAD)"

# 2. venv, dependencies, service files. TZ follows the Mac so her clock matches the user.
MAC_TZ="$(readlink /etc/localtime | sed 's#.*/zoneinfo/##')"
ssh "$BOX" "cd ~/$REMOTE_DIR \
  && { [ -x .venv/bin/python ] || python3 -m venv .venv; } \
  && .venv/bin/python -m pip install -q -r requirements.txt -e . \
  && for u in dafeiyu-browse.timer dafeiyu-browse.service; do \
       systemctl --user disable --now \$u 2>/dev/null; rm -rf ~/.config/systemd/user/\$u ~/.config/systemd/user/\$u.d; done \
  && for u in dafeiyu-wechat.service dafeiyu-nightly.service dafeiyu-nightly.timer; do \
       mkdir -p ~/.config/systemd/user/\$u.d && cp scripts/systemd/\$u ~/.config/systemd/user/; done \
  && for u in dafeiyu-wechat.service dafeiyu-nightly.service; do \
       printf '[Service]\nEnvironment=TZ=%s\n' '$MAC_TZ' > ~/.config/systemd/user/\$u.d/tz.conf; done \
  && printf '[Timer]\nOnCalendar=\nOnCalendar=*-*-* 03:30:00 %s\n' '$MAC_TZ' > ~/.config/systemd/user/dafeiyu-nightly.timer.d/tz.conf \
  && systemctl --user daemon-reload \
  && { systemctl --user is-enabled --quiet dafeiyu-wechat.service && systemctl --user enable --now dafeiyu-nightly.timer >/dev/null && systemctl --user restart dafeiyu-nightly.timer || true; } \
  && .venv/bin/python -m pytest -q 2>&1 | tail -1"
echo "installed; TZ=$MAC_TZ"

# 3. Her memory and keys. Never run with the box's service up: two writers on one SQLite file.
if [ "$WITH_DATA" = 1 ]; then
    ssh "$BOX" "systemctl --user stop dafeiyu-wechat.service 2>/dev/null || true"
    rsync -az .env "$BOX:$REMOTE_DIR/.env"
    rsync -az --delete data/ "$BOX:$REMOTE_DIR/data/"
    echo "copied .env and data/"
fi

if [ "$START" = 1 ]; then
    ssh "$BOX" "loginctl enable-linger \$(whoami) 2>/dev/null || echo 'enable-linger needs: sudo loginctl enable-linger \$(whoami)'; \
      systemctl --user enable --now dafeiyu-nightly.timer dafeiyu-wechat.service && systemctl --user --no-pager status dafeiyu-wechat.service | head -5"
elif [ "$RESTART" = 1 ]; then
    ssh "$BOX" "systemctl --user restart dafeiyu-wechat.service && systemctl --user --no-pager status dafeiyu-wechat.service | head -5"
fi
