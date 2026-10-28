# 她住在寝室的 Ubuntu 机上：怎么部署、看日志、重扫码、备份

> **是什么：** 大肥鱼常驻在寝室 Ubuntu 笔记本（`young-ubuntu`，Tailscale，SSH 别名 `ubuntu-tailscale`）上的操作规程。
> **地位：** 规程（决定 8，2026-10-26）。`scripts/deploy_box.sh` 和 `scripts/systemd/` 按它写。
> **读法：** 查你要做的那件事。

## 0. 她在哪

- 代码 `~/Dafeiyu`（box 上），由 Mac `git push box main` 直接更新工作区（和 Yaqi 仓库同一招：`receive.denyCurrentBranch updateInstead`）。
- 记忆 `~/Dafeiyu/data/fish.db`、微信凭证 `data/wechat.json`、密钥 `.env`：**都在 box 上，box 上的才是真的**。Mac 上 `data/` 是搬家那天的旧拷贝，别再在 Mac 上跑 `fish wechat`（两边同时收微信消息会互相抢）。
- 两个 systemd 用户单元：`dafeiyu-wechat.service`（一直跑；她的空闲时间、天气也在这里面）、`dafeiyu-nightly.timer`（每天 03:30 跑 `fish nightly`）。原来每天 09:30 的 `dafeiyu-browse.timer` 决定 24 撤了，部署脚本会把旧的停掉删掉。时区跟 Mac 一样（部署脚本从 Mac 读，写进 `tz.conf`），所以她的"深夜"和"上午"都是用户的，不是 box 的。

## 1. 常用命令（都在 Mac 上敲）

最省事：`scripts/fish.sh show | notebook | logs | sent | timers | browse`，时间都按 Mac 上 `.env` 的 `TZ` 显示（box 系统时区可以和用户不同；她自己的钟本来就按 `TZ` 走）。下面是展开的写法。

| 要做的事 | 命令 |
|---|---|
| 改了代码，推上去并重启她 | `scripts/deploy_box.sh --restart` |
| 看她在干嘛（实时日志） | `ssh ubuntu-tailscale journalctl --user -u dafeiyu-wechat -f` |
| 看她的状态 | `ssh ubuntu-tailscale systemctl --user status dafeiyu-wechat` |
| 看她记了什么 | `ssh ubuntu-tailscale 'cd Dafeiyu && .venv/bin/python -m fish show'` |
| 手动跑一次夜间整理 | `ssh ubuntu-tailscale 'cd Dafeiyu && .venv/bin/python -m fish nightly'`（同一天跑两次第二次会跳过） |
| 看她的小本本（夜里导出的） | `ssh ubuntu-tailscale cat Dafeiyu/data/notebook_export.md` |
| 看昨晚整理的日志 | `ssh ubuntu-tailscale journalctl --user -u dafeiyu-nightly -n 20` |
| 看她空闲时干了什么 | `fish show` 的"空闲"一节（两周里每样选了几回、最近几段、在读的书）；见闻本身在 `fish show` 或导出文件里 |
| 让她现在就逛一次 | `ssh ubuntu-tailscale 'cd Dafeiyu && .venv/bin/python -m fish browse'`（手动的，一天一次，第二次跳过；平时她想逛才逛） |
| 微信说过期了，重扫码 | 先 `ssh ubuntu-tailscale systemctl --user stop dafeiyu-wechat`，再 `ssh -t ubuntu-tailscale 'cd Dafeiyu && .venv/bin/python -m fish wechat login'`（二维码画在 Mac 的终端里），再 `ssh ubuntu-tailscale systemctl --user start dafeiyu-wechat` |
| 导出她的记忆给试算脚本（`scripts/memory_v2_trial.py`，只读） | 在 box 上 `cd Dafeiyu && .venv/bin/python -c "import json; from dataclasses import asdict; from fish.config import load_settings; from fish.storage import connect; from fish.memory import MemoryStore; c = connect(load_settings().db_path); print(json.dumps({'memories': [asdict(m) for m in MemoryStore(c).alive()], 'episodes': [dict(r) for r in c.execute('SELECT id, started, ended, gist, importance, valence FROM episodes')]}, ensure_ascii=False))" > her_memories.json`，再 scp 到 Mac |
| 备份她的记忆到 Mac | `rsync -az ubuntu-tailscale:Dafeiyu/data/ ~/Dafeiyu/backups/$(date +%F)/` |
| 停掉她 | `ssh ubuntu-tailscale systemctl --user stop dafeiyu-wechat` |
| 不让她先开口 / 改每天上限 | box 的 `~/Dafeiyu/.env` 里加 `FISH_REACH_OUT=0` 或 `FISH_REACH_MAX=1`，然后 `systemctl --user restart dafeiyu-wechat` |
| 送她表情包 | `scp 图.png ubuntu-tailscale:Dafeiyu/data/stickers/inbox/`，夜里她看图起叫法收进相册（也可以直接在微信里发给她，她觉得好玩会自己留） |
| 看她的相册 | `ssh ubuntu-tailscale 'cd Dafeiyu && .venv/bin/python -c "from fish.storage import connect; from fish.memory import StickerAlbum; from pathlib import Path; [print(s.id, s.caption, s.uses) for s in StickerAlbum(connect(Path(\"data/fish.db\")), Path(\"data/stickers\")).all()]"'` |

## 2. 第一次搬家怎么做的（2026-10-26）

1. Mac 上先 Ctrl-C 掉正在跑的 `fish wechat`。
2. `scripts/deploy_box.sh --with-data --start`：推代码 → box 上建 `.venv`、装依赖、跑测试 → 装服务文件和时区 → 把 `.env` 和 `data/` 拷过去（`--with-data` 只在搬家时用，它会用 Mac 的记忆覆盖 box 的）→ `loginctl enable-linger`（让服务不用登录也跑）→ 启动服务和定时器。
3. 在微信上发一句，`journalctl` 里看到她收发。

## 3. 出了事

- **她说回了、他没收到：** `journalctl --user -u dafeiyu-wechat | grep "→"` 每条发出去的消息都有一行，带 message_id 和"凭证还剩几条"。有这一行、他却没收到，是微信服务器吞了或延迟了（10-26 晚出现过，次日恢复；每张对话凭证约 10 条、他 24 小时没说话就丢，见决定 14）。没有这一行，是我们这边没发。

- **服务起不来：** `journalctl --user -u dafeiyu-wechat -n 50`。常见：`.env` 没拷（`DEEPSEEK_API_KEY is empty`）、`data/wechat.json` 没拷（`还没绑微信`）。
- **开机后服务没起：** `loginctl show-user young -p Linger` 要是 `yes`；不是就 `sudo loginctl enable-linger young`（要密码，用户自己敲）。
- **box 重装或换机器：** 把 `data/` 整个拷过去就是她本人；代码重新 push 一遍。
- **想把她搬回 Mac：** box 上停服务，`rsync` 把 `data/` 拉回来，Mac 上跑 `fish wechat`。
