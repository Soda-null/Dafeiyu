# 节点化：像 ROS 那样把她拆开

> **是什么：** 架构稿。把现在"大脑一个文件管一切"的写法，改成 ROS 式的节点 + 消息：每个模块只认约定好的消息，不伸手进别人内部；加新功能是加一个节点，不是改一堆老文件。
> **地位：** 现行方向（用户 2026-10-28 晚："我要的是思路，类似 ros 一样的模块化思想"，"开始第 1 步"）。第 1、2 步做完（10-28）；第 3 步起按 §4 一步一步来，每步用户点头。`architecture_zh.md` §1 已按第 2 步改。
> **读法：** §1 看一眼问题在哪；§2 是节点清单；§3 是消息清单（最要紧的一节）；§4 是怎么一步步搬，每步都能单独做、单独停。

## 0. 一句话

**不是真的多进程 ROS。** 还是一个 Python 进程、一个 SQLite 文件，但代码的组织方式照 ROS 的思路：

| ROS 里的 | 这里对应 | 意思 |
|---|---|---|
| 节点（node） | `src/fish/` 下的一个包 | 各管各的，能单独测、单独换 |
| 话题（topic） | `bus.publish("he_said", ...)` | 一件事发生了，谁关心谁订，发的人不知道谁在听 |
| 服务（service） | 节点 `__init__.py` 里导出的几个函数 | 一问一答，比如"给我这句话相关的记忆" |
| 消息定义（msg） | `src/fish/msgs.py` 里的 dataclass | 合同。改实现不改合同，别的节点一行不动 |
| launch 文件 | `src/fish/app.py` | 唯一一处把节点接起来的地方；谁连谁，一眼看清 |
| 参数服务器 | `config.py` | 已经有了，不动 |

## 1. 现在的问题在哪

规矩是有的（`architecture_zh.md`：跨模块只走 `__init__.py`；大脑不认识电话线），而且守住了：`memory/`、`cottage/`、`world/` 都干净，谁也不 import 别人。**问题集中在一个地方：`brain/respond.py`。**

- 577 行，24 个方法，直接调 memory / mood / cottage / world / persona 里的对象 **85 处**。一轮回话 `handle()` 一个方法 100 多行，自己去翻记忆的表、算心情、读小屋、存聊天、关惦记、收表情包。
- 今天一天的改动（小屋、饿困、当天全文、先开口）**每一项都往这个文件里加东西**。再来两三个功能，它就是你说的屎山。
- `brain/reach.py`、`brain/leisure/free.py`、`routines/nightly.py` 四个文件直接写 SQL（`conn.execute`），绕过了 `memory/` 的接口。
- `routines/nightly.py` 也是同样的枢纽写法：320 行，八步里每步都知道所有模块的内部。

一句话：**模块是分开的，但"谁在什么时候调谁"全攒在两个大文件里。** 加功能 = 改这两个文件。

## 2. 节点清单

现在的包大体就是节点，不用大拆。要做的是**把每个节点的对外接口收窄、写明**，并把两个枢纽文件拆掉。

| 节点 | 管什么 | 对外只给这些（服务） | 订什么（话题） | 发什么（话题） |
|---|---|---|---|---|
| `channels` | 电话线 | `run(handler)` | `she_said` | `he_said` |
| `brain` | 拼提示词、问模型、读回复。**只做这一件事** | `reply(Situation) -> Reply` | `he_said` | `she_said`、`she_noted` |
| `memory` | 记着什么 | `recall(cue, now)`、`card()`、`pacts()`、`note(...)`、`today_chat(now)`、`close_chat(...)` | `he_said`、`she_said`、`she_noted`、`day_ended` | `memory_changed` |
| `mood` | 她此刻的状态 | `now(clock) -> Mood`、`describe()` | `she_said`（她报的心情）、`time_passed`、`she_ate`、`she_slept` | — |
| `cottage` | 屋里的现实 | `view(now)`、`offers(now, mood)`、`act(...)`、`give(...)` | `time_passed` | `home_event`、`she_ate`、`she_slept` |
| `world` | 往外看 | `feeds()`、`search()`、`read()`、`weather()` | — | — |
| `persona` | 她是谁 | `text()`、`stage_rules(stage)` | — | — |
| `leisure` | 空闲时干什么（从 `brain/leisure/` 搬出来成独立节点） | — | `time_passed` | `she_did`、`she_noted` |
| `reach` | 先开口（从 `brain/reach.py` 搬出来） | — | `time_passed`、`home_event`、`he_said` | `she_said` |
| `nightly` | 夜里整理（`routines/`） | — | `day_ended` | `memory_changed` |
| `clock` | 新。一个小节点，每次轮询发 `time_passed`，03:30 发 `day_ended` | — | — | `time_passed`、`day_ended` |
| `bus` | 新。几十行：`subscribe(topic, fn)`、`publish(topic, msg)`，同步调用，按订阅顺序 | — | — | — |

三条铁律（前两条现在就有，第三条是新的）：

1. `brain`、`memory`、`mood` 不许 import `channels`。
2. `memory`、`cottage`、`world` 不调模型。
3. **节点之间只能 import `msgs.py` 和 `bus.py`，以及对方 `__init__.py` 导出的服务。** 不许 import 对方的子文件（`from fish.memory.window import FOLD_BATCH` 这种现在有 26 处，一半藏在函数里面，全部收掉）。不许在节点外写 SQL。`tests/test_skeleton.py` 查。

## 3. 消息清单（合同）

全放 `src/fish/msgs.py`，都是 `@dataclass(frozen=True)`。字段尽量少；要加字段可以，不能改已有字段的意思。

```python
# 话题消息
HeSaid(text, image, file, channel, at)          # 他发来一句（现在的 Incoming）
SheSaid(text, sticker, channel, at, first)       # 她说了一句；first=True 是她先开口
SheNoted(notes, followups, corrections, at)      # 她这轮顺手记的（模型回复里 notes 那几项）
TimePassed(now)                                  # 时钟走了一格（每次轮询）
DayEnded(day, now)                               # 03:30 到了
HomeEvent(line, at, routine)                     # 屋里发生了一件事（买到菜、菜坏了、饭好了）
SheAte(at, how_much)                             # 吃了（小屋发，心情订）
SheSlept(from_, to)                              # 睡了（小屋发，心情订）
SheDid(what, line, result, at)                   # 空闲时干了件事
MemoryChanged(ids, why)                          # 记忆写了 / 改了（现在只有日志用，留着给以后的屏幕）

# 服务的入参 / 出参
Situation(persona, mood, card, pacts, recalled, today_chat, home, world, now)   # brain.reply 的全部输入
Reply(say, sticker, mood_word, notes, followups, asked, corrections, look)       # 已有，不变
```

**`Situation` 是关键。** 现在 `handle()` 里那 100 行"从各处收集东西"的代码，拆成每个节点各自回答一个问题（"你这会儿什么样""这句话让你想起什么"），`app.py` 把答案装进 `Situation` 交给 `brain`。`brain` 从此不认识 `MemoryStore`、`Cottage`、`MoodStore`，只认识 `Situation`。

## 4. 怎么搬：五步，每步能单独做、单独停

每步做完：全部测试过、寝室机上跑一天、`git` 一次提交。任何一步觉得不值，停在那儿也是完整的。

| 步 | 做什么 | 动哪些文件 | 不动什么 | 大概多大 |
|---|---|---|---|---|
| 1 ✅ | **立合同 + 总线。** 写 `msgs.py`、`bus.py`、`clock.py`；`tests/test_skeleton.py` 加第三条铁律的检查：现有 26 处跨节点 import、3 个越界写 SQL 的文件记成老账放过，**新的一律失败**；修掉一处就得从老账里划掉（测试会提醒），清单只会变短 | 新文件为主 | 行为一点不变 | 10-28 做完 |
| 2 ✅ | **拆 `handle()`。** 记忆的回答搬进记忆节点（`memory/recollect.py`：这句话让她想起什么；`memory/daychat.py`：今天的聊天留哪些原文）；她住哪的读法搬进 `world`；纯大脑 `brain/reply.py` 只认 `Situation`（原 `PromptContext` 改名），拼提示词、问、读，不认识任何仓库；`respond.py` 成了接线员：收集 → `Situation` → 大脑 → 记下。还清 8 处老账。**验收**：用寝室机数据拷贝的三个真实时刻，拆前拆后每次模型调用、她的回复、数据库各表的变化逐字节相同；439 个测试一个断言没改。**和原计划不同的一处**：`app.py` 放到第 3 步：`Brain` 被 30 多个测试和脚本 import，现在搬只是改名，等接总线时一起搬 | `brain/respond.py`（577 → 491 行）、`brain/reply.py`、`memory/recollect.py`、`memory/daychat.py`、`world/place.py` | 提示词文本、记忆规则、测试的断言 | 10-28 做完 |
| 3 | **把"先开口""空闲""小屋动作"改成订阅。** 它们订 `TimePassed` / `HomeEvent`，不再由 `respond.tick()` 挨个调 | `reach/`、`leisure/` 成独立节点 | 它们各自内部的规则 | 一天 |
| 4 | **心情只订消息。** 饿困跟着 `TimePassed` / `SheAte` / `SheSlept` 走（决定 32 已经这么定了，这步只是把"小屋改心情"从 `respond.move_time` 搬成订阅） | `mood/`、`cottage/` | 数值 | 半天 |
| 5 | **夜里整理拆成订阅链。** `nightly` 八步变成 `DayEnded` 的八个订阅者，每个一个文件；去掉四处散落的 SQL | `routines/nightly.py` | 每步的提示词和规则 | 一天 |

做完以后，"加一个新功能"长这样：

- **接屏幕**：新节点 `screen/`，订 `SheSaid`、`SheDid`、`HomeEvent`、`MemoryChanged`，画像素画。不改任何老文件。
- **接摄像头**：新节点 `eyes/`，发 `HeSaid(image=...)`。大脑不知道图是从微信来的还是摄像头来的。
- **新的空闲活动**：和现在一样，`leisure/` 加一个文件。
- **换模型 / 加第二个模型**：只在 `brain/llm.py`。

## 5. 不做的事（免得越搬越大）

- 不真的开多进程、不用网络传消息、不引第三方消息库。几十行自己的 `bus.py` 够了；真要换成多进程，只换 `bus.py`。
- 不改记忆的任何规则、不改提示词的文字、不改小屋的数字。这次纯搬家，行为不变，体检分数（`scripts/checkup.py`）前后应该一样，拿它当验收。
- 不一次全搬。第 2 步做完就已经解决了八成的问题，后面三步看状态做。

## 6. 要用户定的

1. 这个方向对不对；五步的顺序要不要调。
2. 第 2 步动静最大，寝室机上会停一会儿（部署重启，几秒）。平时哪天做都行，选一天你不太跟她聊的。
3. 节点、话题这些词要不要在 `glossary_zh.md` 加人话解释（我建议加，一行一个）。
