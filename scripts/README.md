# 脚本

> **是什么：** 会话工具和检查，每个一行。
> **地位：** 索引。新脚本在同一次提交加一行。
> **读法：** 查表。

| 脚本 | 做什么 | 谁跑 |
|---|---|---|
| `check_doc_structure.py` | 查三行卡片、`docs/README.md` 列全、入口文件大小 | 提交钩子（改到文档时）；手动 `python3 scripts/check_doc_structure.py` |
| `new_log.py` | 新建当天 `docs/log/YYYY-MM-DD.md`，已有不覆盖 | 会话结束时 |
| `fish.sh` | 在 Mac 上看 box 上的她，所有时间按本地 `.env` 的 `TZ` 显示：`show`、`notebook`、`logs`、`sent`、`timers`、`browse` | 用户随时 |
| `../install.sh` | 一键安装（仓库根目录）：拿代码、建 `.venv`、问 key / 时区 / 他还是她写 `.env`、自检、扫码绑微信、装开机自启（Linux systemd 用户服务 / macOS launchd）；`update`、`uninstall` | 新用户；`curl … \| bash` 或 `./install.sh` |
| `deploy_box.sh` | 把她推到寝室 Ubuntu 机：push 代码、装 venv、装服务文件和时区；`--with-data` 搬记忆（只在搬家时）、`--start` 启动、`--restart` 改完代码重启 | Mac 上，`docs/box_zh.md` |
| `systemd/` | box 上的服务文件：`dafeiyu-wechat.service`（常驻）、`dafeiyu-nightly.service` + `.timer`（每天 03:30）、`dafeiyu-browse.service` + `.timer`（每天 09:30） | `install.sh` 和 `deploy_box.sh` 装（路径换成实际文件夹） |
