# `src/fish/`：代码

> **是什么：** 每个模块一行；谁依赖谁。模块边界以 `docs/architecture_zh.md` 为准。
> **地位：** 索引。新模块在同一次提交加一行。
> **读法：** 查表。

| 模块 | 做什么 | 状态（10-26） |
|---|---|---|
| `config.py` | 从 `.env` 读密钥、模型名、数据库路径；别处不碰环境变量。`TZ` 没写就用她家的时区（`data/home/home.json`） | 能用 |
| `storage/` | SQLite 连接和建表（八张表，`memory_design_zh.md` §9） | 能用 |
| `persona/` | 读 `docs/persona_zh.md`：底子（每轮原样进提示词）和"熟悉程度"三档（只有当前档进，决定 11） | 能用 |
| `memory/` | 只有数据和数学，不调模型：`stability`（遗忘公式；决定 21 起牢固度从"说的是什么"和"多触动"算，一辈子的钉住）、`longterm`（长期条目：加 / 想起 / 改口 / 合并 / 底牌；`note` 是写之前挑：关于聊天本身的不记、重复的加固旧的、规律和相处方式各 20 条上限，决定 19；重复的事记次数、攒到 3 / 6 / 12 回夜里改写成大意，决定 20）、`retrieval`（召回：两道门 + 三项打分；`BigramEmbedder` 不用模型）、`window`（最近 N 轮 + 折叠）、`episodes`（一次聊天）、`prospective`（惦记）、`relationship`（关系账）、`diary` | 能用，30 个测试 |
| `mood/` | 性格最快的一层（决定 13）：`node.py` 的 `MoodNode` 只听 `MoodMoved` 改饿、精力、无聊（节点化第 4 步）；精力、无聊、饿每轮变，时钟加偏移不存，`log` 每轮记一行，`rest(tone, drive)` 夜里回到阶段定的基线；`stage_of` 按亲近值分档 | 能用 |
| `memory/recollect.py`、`memory/daychat.py` | 节点化第 2 步：记忆节点给大脑的唯一回答。`Recollector.recollect` 是"他这句话让她想起什么"（底牌、碰到的、约定、召回、翻聊天摘要、"今天"一节、到期惦记、见闻、日记、阶段）；`day_chat` 是今天聊过的哪些还留原文（决定 32） | 能用 |
| `memory/when.py` | 按时间想起（第二版第 5 步）："昨晚""上周三""一月初"读成日子，那几天的记忆算相关（时间越窄加得越多）；`TimeCued` 包在别的找法外面，第三版第 2 步起每轮聊天都用。第三版第 3 步加了反过来的：`day_of` 读一条笔记说的是哪天（"明天""下下周二"也认，填 `happened_on`）、`fix_weekday` 把和旁边"周X"对不上的日期挪过去、`spoken` 把日子说成"上周三 1月13日" | 能用 |
| `memory/today.py` | 第三版第 3 步：每轮提示词里的"今天"那一节，纯代码：这周下周每天几号、生日今天或 3 天内、他说过今天 / 明天要做的事；加上第 6 步的星期几规律和"他几点来" | 能用，`tests/test_v3_today.py`、`tests/test_v3_patterns.py` |
| `memory/patterns.py` | 第三版第 6 步：程序数他的习惯，不调模型。夜里数他某个星期几总说的话（小周周五的"糖醋排骨"、小林周三的"吉他课"），存进关系账的 `patterns`，带"还在 / 停了"；每轮从他每天第一条消息的钟点算"他一般几点来"那一行。只在那个星期几、或他问"一般 / 平时 / 每周"时给她看 | 能用，`tests/test_v3_patterns.py` |
| `memory/scrub.py` | 第三版第 5 步：秘密过滤，纯规则。`secret` 认 6 位以上连着的数字和"密码、验证码、卡号"这类词，`redact` 去掉带它的那一句；笔记、改口、结果、惦记、摘要、日记的写入口都用 | 能用，`tests/test_v3_writing.py` |
| `memory/pages.py` | 第三版第 8 步（等用户批）：翻聊天摘要，纯代码。他问"记得吗 / 叫啥 / 咋样"或点了过去的日子（"昨晚""上周五"）才翻；按聊天的摘要（30 天后不重要的只剩一句话）和收尾记的标签找，最多 2 页、每页 160 字，读出来再过一遍秘密过滤；从不读聊天原话。`.env` 的 `FISH_PAGES` 开关 | 能用，`tests/test_v3_pages.py` |
| `memory/pacts.py` | 第三版第 4 步：认承诺和外号的固定词（只认聊天里、收尾时写的笔记），谁答应的；`triggered` 看他这句碰到了哪条约定的标签。纯函数，`longterm.note` 和每轮的约定块用 | 能用，`tests/test_v3_pacts.py` |
| `memory/phase.py` | 性格中间层：基调、劲头、在意的事、一句话，`update` 每晚八成旧两成新 | 能用 |
| `memory/traits.py` | 性格底色层：五根有界滑杆，`apply` 一次最多挪 0.15，`describe` 只说挪得明显的；每月的"回头看"笔记 | 能用 |
| `memory/relationship.py` | 关系账：认识天数、连续天数、**亲近值**按天涨（每轮 +0.3、开心 +1，但一天最多 +2，熟了以后 +1、很熟以后 +0.8；没聊的日子 −0.5；决定 17） | 能用 |
| `brain/` | 所有模型调用都在这：`respond.py` 是接线员（节点化第 2 步）：问各节点要答案装成 `Situation` → 交给 `reply.py` → 记下这一轮（收尾旧情景、折叠也在这）；`reply.py` 是大脑本身，只认 `Situation`：拼提示词、问、读回复、查一下；`prompt.py` 按 `prompts/*.md` 渲染；`budget.py` 字数预算；`parse.py` 读 JSON 回复；`llm.py`：`DeepSeekLLM`（JSON 模式）、`FakeLLM`、`CountingLLM`（数调用，体检用） | 能用，寝室机上真跑着 |
| `brain/prompts/` | `gist.md`（夜里把反复的事改写成大意，决定 20）；聊天：`chat.md`（人设 + 怎么回 + 输出格式 + 底牌 / 日记 / 现在 / 想起 / 惦记 / 摘要）、`fold.md`（折叠窗口）、`close_episode.md`（收尾聊天）；夜里：`merge.md`（合并重复）、`contradictions.md`（新事实取代旧的）、`reflect.md`（反思）、`diary.md`（日记和生活线）；用户能直接改 | 能用 |
| `brain/consolidate.py` | 夜里的四次模型调用（合并、取代、反思、日记），回复坏了就当"今晚不做" | 能用 |
| `brain/world.py` | 逛的两次模型调用：从今天的标题里挑最多 3 条、看完写见闻和新念头（`prompts/browse_pick.md`、`browse_read.md`）；`brain/ask.py` 是它们共用的"问一句拿 JSON" | 能用 |
| `brain/leisure/` | 她的空闲时间（决定 24，"你可以"不是"你必须"）：`free.py` 是门（白天、他半小时没说话、一天 3 段、隔 3 小时）和一段空闲的流程（摆菜单、打乱、问她挑、选了事再写见闻）；每样能做的事一个文件：`feeds.py`（翻新闻、刷 B 站）、`book.py`（维基文库读书，带书签）、`curious.py`（查好奇的）。**加新的**：写一个 `Activity` 子类（`base.py`），在 `__init__.py` 的 `default_activities` 加一行 | 能用，10 个测试 |
| `memory/pastimes.py` | 书签（在读的书，30 天没碰算弃了）和每段空闲的记录 `leisure_log` | 能用 |
| `brain/reach.py` | 她先开口（决定 10）：`ReachNode` 是节点（第 3 步），订"时间走了"、发出去就在总线上发 `SheSaid`；`ReachPolicy` 规则的门和由头（见闻、到期的惦记、太久没聊、纪念日、无聊、家里刚发生的事；状态存关系账的 `reach_*`），`Reacher` 问她一次说不说（`prompts/reach_out.md`）；`respond.py` 的 `tick(send)` 串起来 | 能用 |
| `brain/respond.py` 的图片部分 | 他发的图作为图片给模型（只能放在用户那条消息里）；`image_note` 存进对话；`keep_sticker` 收进相册；`sticker` 编号 → `Outgoing` 带图；`prompts/sticker_caption.md` 给 inbox 的图起叫法 | 能用，真机验证过 |
| `world/` | 只管"看"，不调模型：`feeds`（RSS / Atom）、`bilibili`（热门、分区榜、热评）、`wiki`（中文维基查一下，`Searcher` 协议）、`reader`（网页 → 正文）、`files`（他分享的 PDF / Word / 文本 → 正文，决定 23）、`sources.json` + `sources.py`（订阅源、取今天的、点开一条）、`wikisource`（维基文库按书名找书、按段读，决定 24）、`days`（节气、节假日和调休，表缓存在 `data/home/`） | 能用 |
| `world/place.py` + `routines/outside.py` | 她住哪（决定 15）：定位到街区、每天天气、附近的店、街区地图拼图并让她看一次 | 能用 |
| `routines/` | `nightly.py` 八步（第三版加了 6b：数星期几规律），一个"鱼日"（03:30 到次日 03:30）只跑一次；`browse.py` 只剩手动的 `fish browse`（决定 24 起她空闲时想逛才逛）；`outside.py` 天气和节假日表，微信服务每小时看一眼、一天真取一次；`export.py` 写 `data/notebook_export.md`；`runs.py` 记每个例行做到哪天 | 能用 |
| `cottage/` | 她的湖边小屋（决定 26），不调模型：`node.py` 的 `RoomNode` 是节点（节点化第 4 步）：每格让屋子往前走，在总线上喊 `MoodMoved` / `SheAte` / `SheSlept` / `HomeEvent`，`lately` 回答"最近屋里出了什么事"、`view` 给聊天看的几行；`rules.py` 是数字（和 `docs/cottage_rules_zh.md` 一起改）、菜店的货、`layout` 读规则文件第 1 节给她看；`room.py` 是现状文件 `data/cottage/now.json`：`advance` 让时间走（睡觉、饭点吃饭、菜放坏）、`offers` / `act` 是她能做的事、`give` / `put_on_sill` 是他放东西、`for_chat` / `for_leisure` 是她看见的几行；`invented_act` 认她笔记里编的做过的事（有屋子以后不记）。`brain/leisure/cottage.py` 把动作摆进空闲菜单；`FISH_COTTAGE` 开关，默认开（决定 28） | 能用，`tests/test_cottage.py` |
| `msgs.py` | 节点之间传的消息（合同，`nodes_design_zh.md` §3）：`HeSaid`、`SheSaid`、`TimePassed`、`DayEnded`、`HomeEvent` 等，都不可改；不 import 项目里任何东西 | `TimePassed`、`SheSaid` 已在用 |
| `bus.py` | 总线：`subscribe(消息类, 函数)`、`publish(消息)`；话题就是消息的类；一个订阅者出错不影响别的，测试里一起报、服务里记日志 | 第 3 步起接进服务 |
| `clock.py` | 时钟节点：每格发 `TimePassed`（手动拨回去也发），往前跨过 03:30 发 `DayEnded`（睡了几晚就补几天，同一天不发两次）；`day_of` 算一个时刻属于她哪一天 | 第 3 步起接进服务：`Brain.tick` 就是走一格 |
| `app.py` | 启动文件（节点化第 3 步）：一张表写谁订什么、按什么顺序；只认 `bus` 和 `msgs`，节点作为参数交进来。**加一个跟时间或她的话有关的新功能 = 这里加一行** | 能用 |
| `messages.py` | 电话线和大脑之间传的 `Incoming(text, image, file)` / `Outgoing(text, sticker)`，和图片类型探测、data URL | 能用 |
| `channels/` | `terminal.py`；`ilink.py` 腾讯 ClawBot 的 HTTP 协议（照官方插件 2.4.10：扫码登录、长轮询 `getupdates`、`sendmessage`、正在输入；收图下载解密、上传发图，AES-128-ECB），`wechat.py` 微信电话线（`login` 扫码存凭证；`WeChatChannel` 只回主人、去重、每行一个气泡、文字后发表情包、出错退避、-14 提示重扫；每轮轮询之间 `tick` 让她有机会先开口，`push` 用上次的对话凭证发） | 文字和图片真机验证过 |
| `memory/stickers.py` | 表情包相册：存图、起叫法、按用过次数排、记用过；同一张图按指纹只收一次；`offer` 每轮给她看常用的 12 张加随机换的其余，相册再大也轮得到没用过的 | 能用 |
| `routines/stickers.py` | 送她表情包：`import_folder` 把一个文件夹的图拷进收件箱，`adopt_inbox` 一张张让她起叫法收下（`fish stickers` 当场全收，夜里一晚 10 张） | 能用 |
| `__main__.py` | `python3 -m fish [chat \| nightly \| browse \| show \| stickers [文件夹] \| cottage [put 东西 \| sill 东西] \| wechat [login]]` | 能跑 |

依赖方向：`channels → brain → {persona, memory, mood, world, cottage} → storage`；`routines → {memory, mood, brain, world}`；`world` 只用标准库。`brain/`、`memory/`、`mood/` 不许 import `channels/`（`tests/test_skeleton.py` 查）；`memory/` 里没有任何模型调用，所以它的测试不用密钥。
