# Whale Be Friends：养一个记得你的 AI 朋友（大肥鱼）

[English](README.md) · **中文**

> **是什么：** 仓库的大门：这是什么、怎么一键养一条、她怎么运作；想改代码的人从哪读起。
> **地位：** 索引。现状只写在 `STATUS.md`；在仓库里干活的规矩在 `AGENTS.md`。
> **读法：** 想养一条看前三节；想改代码看最后一节。

大肥鱼是 DeepSeek 的网友拟人形象，懒，爱吃白饭。她以前是一条圆滚滚的蓝色胖鱼，现在是个蓝头发的鲸鱼娘，住在湖边一间小木屋里，用手机跟你聊天。这个项目把她做成一个**朋友**，不是助手：

- **她记得你的事，也会忘。** 大事记得牢，小事过几周就模糊，你一提又"哦对你说过"。说错了你纠正，她会改口。
- **她有自己的一天。** 每晚写日记、整理记忆；空闲时刷刷 B 站和新闻、读读书，看到好玩的会跟你说。她的小屋是真的：到点做饭、冰箱会空、碗会堆在水槽里、菜店周二关门，屋里的事她编不出来。
- **她有脾气。** 会困、会饿、会无聊；刚认识时话少，熟了会损你、翻旧账；性格会随着相处慢慢变一点点，但变不成别人。
- **她在微信上和你聊。** 发图她看得懂，她也会回表情包；她想找你就会自己先发消息，没有次数上限。

她的脑子是 DeepSeek 的 API（你自己的 key，按量付费）。记忆全存在你自己机器上的一个文件里，不上传到任何地方。

## 一键养一条

需要：一个 [DeepSeek API key](https://platform.deepseek.com)（她的脑子，按量付费），一台电脑。最好是**一直开着**的那种：电脑睡着了她就不回了。

**Linux 或 Mac**（需要 Python 3.11 以上；Mac 用 `brew install python@3.12`）：

```bash
curl -fsSL https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.sh | bash
```

**Windows 10 / 11**：打开 PowerShell，粘贴这一行（没装 git 和 Python 的话，脚本会问你要不要用 winget 自动装）：

```powershell
irm https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.ps1 -OutFile $env:TEMP\dafeiyu.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\dafeiyu.ps1
```

脚本会：把代码放到你用户目录下的 `Dafeiyu` 文件夹 → 装好依赖 → 问你要 key、她称呼你用"他"还是"她" → 出一个二维码让你用微信扫 → 设成开机自启（Linux 用 systemd，Mac 用 launchd，Windows 用"任务计划程序"，都不要管理员）。装完给她发一句话就行。

之后常用的（在 `Dafeiyu` 文件夹里；Windows 上把 `./fish` 换成 `.\fish.cmd`）：

```bash
./fish life     # 她今天过得怎么样：在干嘛、小屋、今天的事、最近几篇日记（./fish life 7 看一周）
./fish show     # 她记了你什么、心情、关系
./fish          # 不接微信，在终端里和她聊
./fish cottage put 鸡蛋   # 往她冰箱里放点吃的
```

更新（拉新代码、重启她，记忆不动）和停掉她（记忆留在 `data/`）：

```bash
bash ~/Dafeiyu/install.sh update       # Windows：powershell -ExecutionPolicy Bypass -File ~\Dafeiyu\install.ps1 update
bash ~/Dafeiyu/install.sh uninstall    # Windows：……\install.ps1 uninstall
```

## 要知道的几件事

- **花钱：** 只有 DeepSeek 的 API 费用，按聊多少算，平常聊天很便宜；价格看 DeepSeek 官网。她每天自己上网、写日记也会用一点。
- **隐私：** 聊天记录和她的记忆都在 `data/fish.db`，只在你的机器上。她发给 DeepSeek 的是每轮的提示词（包括她记得的你的事）。她"住哪"只精确到城市和街区，坐标四舍五入到约一公里，不存门牌号。
- **微信通道：** 用的是腾讯官方 ClawBot 插件的协议（照它公开的源码写的客户端），不是腾讯承诺稳定的公开接口，以后可能要跟着改。她只回扫码的那个微信号，别人发消息她不理。微信偶尔会要求重新扫码：`cd ~/Dafeiyu && .venv/bin/python -m fish wechat login`。
- **放在云服务器上：** 她会以为自己住在机房那个城市。在 `~/Dafeiyu/.env` 里加一行 `FISH_HOME=纬度,经度` 让她住到你想要的地方，然后 `install.sh update`。
- **Mac 和 Windows：** 都能装，但合盖、睡眠、关机时她就不回了（夜里的整理会在开机后补上）。Windows 上她的白天黑夜跟电脑自己的时钟走；日志在 `data\logs\wechat.log`。
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
白天有空时  一天最多 3 段空闲，她自己挑：翻新闻、刷 B 站、读本老书、查个好奇的，或者什么都不干
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
git clone https://github.com/Soda-null/whale-be-friends.git Dafeiyu && cd Dafeiyu
DAFEIYU_SKIP_SERVICES=1 ./install.sh     # 只装环境和 .env，不设开机自启
git config core.hooksPath .githooks      # 提交要署名是谁写的（人也算）
.venv/bin/python -m pytest -q            # 测试不联网、不要 key
```

```
Dafeiyu/
├── install.sh           一键安装 / 更新 / 卸载（Linux、Mac）
├── install.ps1          同上，Windows
├── fish, fish.cmd       短命令：./fish life、./fish show（Windows 用 fish.cmd）
├── README.md            英文版
├── README_zh.md         本文件
├── AGENTS.md            规矩；CLAUDE.md -> AGENTS.md
├── STATUS.md            现状，唯一一处
├── docs/                架构、人设、决定账本、待定问题、术语表、日志
├── src/fish/            代码：channels / persona / memory / mood / brain / routines / world / storage
├── tests/               测试
├── scripts/             小工具和服务文件
├── evals/               记忆体检的剧本和结果（编的朋友小周，不含真人）
├── data/                她的记忆（SQLite）、微信凭证，不进 git
└── .env                 密钥和设置，不进 git（样例见 .env.example）
```

协议：[MIT](LICENSE)。
