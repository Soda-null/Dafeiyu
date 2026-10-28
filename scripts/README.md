# 脚本

> **是什么：** 会话工具和检查，每个一行。
> **地位：** 索引。新脚本在同一次提交加一行。
> **读法：** 查表。

| 脚本 | 做什么 | 谁跑 |
|---|---|---|
| `check_doc_structure.py` | 查三行卡片、`docs/README.md` 列全、入口文件大小 | 提交钩子（改到文档时）；手动 `python3 scripts/check_doc_structure.py` |
| `new_log.py` | 新建当天 `docs/log/YYYY-MM-DD.md`，已有不覆盖 | 会话结束时 |
| `fish.sh` | 在 Mac 上看 box 上的她，所有时间按本地 `.env` 的 `TZ` 显示：`show`、`notebook`、`logs`、`sent`、`timers`、`browse`、`stickers <文件夹>`（把 Mac 上一个文件夹的图送给她，她当场起名收下） | 用户随时 |
| `checkup.py` | 记忆体检（决定 18）：按 `evals/` 里的剧本在临时库里喂她、每晚整理、到点问、裁判打五档，写报告到 `evals/results/`；`--days 30 --no-final` 是短版 | 改记忆规则前后手动跑，花钱 |
| `recall_bench.py` | 离线比几种找记忆的办法（第二版第 5 步，第三版第 0 步加开关）：拿体检留下的库和剧本，每问看答案在当天记没记下、各种找法能不能排进前 6；`--cue his\|his+hers` 找的时候只用他这句还是拼上她上一句，`--skip-card` 底牌上的算找到、不占名额，`--vectors` 加上句子模型算好的向量就多比"按意思"；小周、小林两个剧本都能用 | 改找记忆的办法前后手动跑，不花钱 |
| `write_coverage.py` | 剧本里每件事写到了哪一层（第三版第 0 步）：笔记、聊天摘要、还是只在他的原话里，第几天第一次出现、问的时候笔记里有没有；某一问自己带了认法（比如"考得咋样"只认分数）就单独成一行，体检自己问的话不算他说过；不该记的词（密码）在她写的东西里几处。把"没记下"和"没找到"分开 | 体检跑完手动跑，不花钱 |
| `memory_v2_trial.py` | 记忆第二版的试算（`docs/memory_v2_zh.md` §6）：给一份她记忆的 JSON 导出，问模型一次打标签，按新旧规则推算几天后清楚 / 模糊 / 想不起 | 调规则时手动跑 |
| `../install.sh` | 一键安装（仓库根目录）：拿代码、建 `.venv`、问 key / 时区 / 他还是她写 `.env`、自检、扫码绑微信、装开机自启（Linux systemd 用户服务 / macOS launchd）；`update`、`uninstall` | 新用户；`curl … \| bash` 或 `./install.sh` |
| `deploy_box.sh` | 把她推到寝室 Ubuntu 机：push 代码、装 venv、装服务文件和时区；`--with-data` 搬记忆（只在搬家时）、`--start` 启动、`--restart` 改完代码重启 | Mac 上，`docs/box_zh.md` |
| `systemd/` | box 上的服务文件：`dafeiyu-wechat.service`（常驻）、`dafeiyu-nightly.service` + `.timer`（每天 03:30）；原来的 `dafeiyu-browse` 决定 24 撤了，两个脚本会清掉旧的 | `install.sh` 和 `deploy_box.sh` 装（路径换成实际文件夹） |
