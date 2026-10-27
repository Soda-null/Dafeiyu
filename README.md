# 大肥鱼（Dafeiyu）：养一条住在你电脑里的 AI 朋友

> **是什么：** 仓库的大门：这是什么、怎么一键养一条、她怎么运作；想改代码的人从哪读起。
> **地位：** 索引。现状只写在 `STATUS.md`；在仓库里干活的规矩在 `AGENTS.md`。
> **读法：** 想养一条看前三节；想改代码看最后一节。

大肥鱼是 DeepSeek 的网友拟人形象：一条圆滚滚的蓝色胖鱼，懒，爱吃白饭。这个项目把她做成一个**朋友**，不是助手：

- **她记得你的事，也会忘。** 大事记得牢，小事过几周就模糊，你一提又"哦对你说过"。说错了你纠正，她会改口。
- **她有自己的一天。** 每晚写日记、整理记忆；每天上午刷刷 B 站和新闻，看到好玩的会跟你说；知道自己住的城市今天什么天气、楼下有什么店。
- **她有脾气。** 会困、会饿、会无聊；刚认识时话少，熟了会损你、翻旧账；性格会随着相处慢慢变一点点，但变不成别人。
- **她在微信上和你聊。** 发图她看得懂，她也会回表情包；一天最多主动找你两次。

她的脑子是 DeepSeek 的 API（你自己的 key，按量付费）。记忆全存在你自己机器上的一个文件里，不上传到任何地方。

## 一键养一条

需要：一台**一直开着**的 Linux 或 Mac（寝室的旧笔记本、云服务器都行），Python 3.11 以上，一个 [DeepSeek API key](https://platform.deepseek.com)。

```bash
curl -fsSL https://raw.githubusercontent.com/Soda-null/Dafeiyu/main/install.sh | bash
```

脚本会：把代码放到 `~/Dafeiyu` → 装好依赖 → 问你要 key、你住的时区、她称呼你用"他"还是"她" → 出一个二维码让你用微信扫 → 设成开机自启。装完给她发一句话就行。

之后常用的：

```bash
cd ~/Dafeiyu && .venv/bin/python -m fish show   # 看她记了你什么、心情、日记
bash ~/Dafeiyu/install.sh update                 # 更新代码并重启她（记忆不动）
bash ~/Dafeiyu/install.sh uninstall              # 停掉她（记忆留在 ~/Dafeiyu/data/）
```

不想接微信，也可以只在终端里聊：`cd ~/Dafeiyu && .venv/bin/python -m fish`。

## 要知道的几件事

- **花钱：** 只有 DeepSeek 的 API 费用，按聊多少算，平常聊天很便宜；价格看 DeepSeek 官网。她每天自己上网、写日记也会用一点。
- **隐私：** 聊天记录和她的记忆都在 `data/fish.db`，只在你的机器上。她发给 DeepSeek 的是每轮的提示词（包括她记得的你的事）。她"住哪"只精确到城市和街区，坐标四舍五入到约一公里，不存门牌号。
- **微信通道：** 用的是腾讯官方 ClawBot 插件的协议（照它公开的源码写的客户端），不是腾讯承诺稳定的公开接口，以后可能要跟着改。她只回扫码的那个微信号，别人发消息她不理。微信偶尔会要求重新扫码：`cd ~/Dafeiyu && .venv/bin/python -m fish wechat login`。
- **放在云服务器上：** 她会以为自己住在机房那个城市。在 `~/Dafeiyu/.env` 里加一行 `FISH_HOME=纬度,经度` 让她住到你想要的地方，然后 `install.sh update`。
- **Mac：** 能装，但合盖睡着时她就不回了。
- **改她的性格：** 人设在 [`docs/persona_zh.md`](docs/persona_zh.md)，是写给她看的大白话，直接改，改完 `install.sh update`。
- 这是粉丝做的小项目，和 DeepSeek、腾讯都没有关系。

## 她是怎么运作的

```
微信 ──> 电话线（channels）──> 大脑（brain）──> DeepSeek
                                 │
              记忆（memory）、心情（mood）、人设（persona）、外面的世界（world）
                                 │
                         data/fish.db（SQLite）

每晚 03:30  夜间整理：写日记、合并重复的记忆、新事实取代旧的、每周反思、回到阶段的心情基线
每天 09:30  上网逛一会儿：从订阅源里挑最多 3 条点开看，记成"见闻"
每轮聊天    挑出相关的记忆 + 最近的对话 + 当下的心情 → 一次模型调用 → 回话、随手记、要惦记的事
```

细节：[架构](docs/architecture_zh.md) · [记忆怎么设计的](docs/memory_design_zh.md)（遗忘曲线、想起来会记得更牢、夜里整理） · [她怎么上网](docs/world_design_zh.md) · [每个设计决定和原因](docs/decisions.md)。

## 想改代码

这个仓库是和 AI 编程助手（Claude Code）一起写的，文档也是写给 AI 和人一起读的。按顺序读：

1. [`AGENTS.md`](AGENTS.md) — 在这个仓库里干活的规矩（`CLAUDE.md` 是它的软链接）。
2. [`STATUS.md`](STATUS.md) — 现状：做到哪、下一步。
3. [`docs/architecture_zh.md`](docs/architecture_zh.md) — 七个模块、一条消息怎么流过去。
4. [`docs/README.md`](docs/README.md) — `docs/` 下每份文件是什么。

```bash
git clone https://github.com/Soda-null/Dafeiyu.git && cd Dafeiyu
DAFEIYU_SKIP_SERVICES=1 ./install.sh     # 只装环境和 .env，不设开机自启
git config core.hooksPath .githooks      # 提交要署名是谁写的（人也算）
.venv/bin/python -m pytest -q            # 测试不联网、不要 key
```

```
Dafeiyu/
├── install.sh           一键安装 / 更新 / 卸载
├── README.md            本文件
├── AGENTS.md            规矩；CLAUDE.md -> AGENTS.md
├── STATUS.md            现状，唯一一处
├── docs/                架构、人设、决定账本、待定问题、术语表、日志
├── src/fish/            代码：channels / persona / memory / mood / brain / routines / world / storage
├── tests/               测试
├── scripts/             小工具和服务文件
├── data/                她的记忆（SQLite）、微信凭证，不进 git
└── .env                 密钥和设置，不进 git（样例见 .env.example）
```

协议：[MIT](LICENSE)。
