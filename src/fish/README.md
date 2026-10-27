# `src/fish/`：代码

> **是什么：** 每个模块一行；谁依赖谁。模块边界以 `docs/architecture_zh.md` 为准。
> **地位：** 索引。新模块在同一次提交加一行。
> **读法：** 查表。

| 模块 | 做什么 | 状态（10-26） |
|---|---|---|
| `config.py` | 从 `.env` 读密钥、模型名、数据库路径；别处不碰环境变量 | 能用 |
| `storage/` | SQLite 连接和建表（八张表，`memory_design_zh.md` §9） | 能用 |
| `persona/` | 读 `docs/persona_zh.md`：底子（每轮原样进提示词）和"熟悉程度"三档（只有当前档进，决定 11） | 能用 |
| `memory/` | 只有数据和数学，不调模型：`stability`（遗忘公式）、`longterm`（长期条目：加 / 想起 / 改口 / 合并 / 底牌）、`retrieval`（召回：两道门 + 三项打分；`BigramEmbedder` 不用模型）、`window`（最近 N 轮 + 折叠）、`episodes`（一次聊天）、`prospective`（惦记）、`relationship`（关系账）、`diary` | 能用，30 个测试 |
| `mood/` | 性格最快的一层（决定 13）：精力、无聊、饿每轮变，时钟加偏移不存，`log` 每轮记一行，`rest(tone, drive)` 夜里回到阶段定的基线；`stage_of` 按亲近值分档 | 能用 |
| `memory/phase.py` | 性格中间层：基调、劲头、在意的事、一句话，`update` 每晚八成旧两成新 | 能用 |
| `memory/traits.py` | 性格底色层：五根有界滑杆，`apply` 一次最多挪 0.15，`describe` 只说挪得明显的；每月的"回头看"笔记 | 能用 |
| `memory/relationship.py` | 关系账：认识天数、连续天数、**亲近值**（每轮 +0.5、开心 +2、没聊的日子 −1） | 能用 |
| `brain/` | 所有模型调用都在这：`respond.py` 每轮流程（收尾旧情景 → 挑 → 拼 → 问 → 记 → 心情 → 折叠）；`prompt.py` 按 `prompts/*.md` 渲染；`budget.py` 字数预算；`parse.py` 读 JSON 回复；`llm.py`：`DeepSeekLLM`（JSON 模式）和 `FakeLLM` | 能用，还没用真模型验过 |
| `brain/prompts/` | 聊天：`chat.md`（人设 + 怎么回 + 输出格式 + 底牌 / 日记 / 现在 / 想起 / 惦记 / 摘要）、`fold.md`（折叠窗口）、`close_episode.md`（收尾聊天）；夜里：`merge.md`（合并重复）、`contradictions.md`（新事实取代旧的）、`reflect.md`（反思）、`diary.md`（日记和生活线）；用户能直接改 | 能用 |
| `brain/consolidate.py` | 夜里的四次模型调用（合并、取代、反思、日记），回复坏了就当"今晚不做" | 能用 |
| `brain/world.py` | 逛的两次模型调用：从今天的标题里挑最多 3 条、看完写见闻和新念头（`prompts/browse_pick.md`、`browse_read.md`）；`brain/ask.py` 是它们共用的"问一句拿 JSON" | 能用 |
| `brain/reach.py` | 她先开口（决定 10）：`ReachPolicy` 规则的门和由头（状态存关系账的 `reach_*`），`Reacher` 问她一次说不说（`prompts/reach_out.md`）；`respond.py` 的 `tick(send)` 串起来 | 能用 |
| `brain/respond.py` 的图片部分 | 他发的图作为图片给模型（只能放在用户那条消息里）；`image_note` 存进对话；`keep_sticker` 收进相册；`sticker` 编号 → `Outgoing` 带图；`prompts/sticker_caption.md` 给 inbox 的图起叫法 | 能用，待真机验证 |
| `world/` | 只管"看"，不调模型：`feeds`（RSS / Atom）、`bilibili`（热门、分区榜、热评）、`wiki`（中文维基查一下，`Searcher` 协议）、`reader`（网页 → 正文）、`sources.json` + `sources.py`（订阅源、取今天的、点开一条） | 能用 |
| `world/place.py` + `routines/outside.py` | 她住哪（决定 15）：定位到街区、每天天气、附近的店、街区地图拼图并让她看一次 | 能用 |
| `routines/` | `nightly.py` 八步，一个"鱼日"（03:30 到次日 03:30）只跑一次；`browse.py` 每天 09:30 起逛一次；`export.py` 写 `data/notebook_export.md`；`runs.py` 记每个例行做到哪天 | 能用 |
| `messages.py` | 电话线和大脑之间传的 `Incoming(text, image)` / `Outgoing(text, sticker)`，和图片类型探测、data URL | 能用 |
| `channels/` | `terminal.py`；`ilink.py` 腾讯 ClawBot 的 HTTP 协议（照官方插件 2.4.10：扫码登录、长轮询 `getupdates`、`sendmessage`、正在输入；收图下载解密、上传发图，AES-128-ECB），`wechat.py` 微信电话线（`login` 扫码存凭证；`WeChatChannel` 只回主人、去重、每行一个气泡、文字后发表情包、出错退避、-14 提示重扫；每轮轮询之间 `tick` 让她有机会先开口，`push` 用上次的对话凭证发） | 文字真机验证过；图片待验证 |
| `memory/stickers.py` | 表情包相册：存图、起叫法、按用过次数排、记用过 | 能用 |
| `__main__.py` | `python3 -m fish [chat \| nightly \| browse \| show \| wechat [login]]` | 能跑 |

依赖方向：`channels → brain → {persona, memory, mood, world} → storage`；`routines → {memory, mood, brain, world}`；`world` 只用标准库。`brain/`、`memory/`、`mood/` 不许 import `channels/`（`tests/test_skeleton.py` 查）；`memory/` 里没有任何模型调用，所以它的测试不用密钥。
