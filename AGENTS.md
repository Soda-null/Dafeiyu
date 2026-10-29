# 在这个仓库里干活的规矩（给 Claude Code、Codex、DeepSeek 和人）

> **是什么：** 任何 AI 或人在这个仓库里写代码、写文档、提交时要守的规矩，一页写完。
> **地位：** 现行（用户 2026-10-26：照 Yaqi 仓库的结构搬过来，但做轻）。`CLAUDE.md` 是它的软链接。
> **读法：** 每个新会话从头读一遍，很短。

## 这个项目要做成什么

一个像**朋友**、不像工具的 AI：大肥鱼。衡量标准不是"能不能帮用户办事"，而是"聊久了像不像一个真的认识你的人"。所以优先级永远是：**记忆 > 心情和自己的生活 > 说话像她 > 功能**。接微信只是换一条"电话线"，不是目标。

## 每个会话

- **开始：** `git status`、`git log --oneline | head`，读 `STATUS.md`。树里有没提交的改动，是别人没做完的活：不要回退、不要收拾；挡路就说一声停下。
- **结束：** 把做完的都提交；不留脏树。当天做了什么，写一条到 `docs/log/YYYY-MM-DD.md`（`python3 scripts/new_log.py` 建文件）。
- **提交署名：** 消息末尾单独一行 `Agent: claude-code` / `Agent: codex` / `Agent: deepseek` / `Agent: human`。`.githooks/commit-msg` 会拦没署名的提交；每个克隆跑一次 `git config core.hooksPath .githooks`。
- **提交第一行 100 字以内**，说改了什么；细节放正文。

## 文档

- 现状只写在 `STATUS.md`，别处链接过去，不抄。
- 每份文档开头三行卡片（是什么 / 地位 / 读法），写法在 `docs/writing_guide_zh.md`；`scripts/check_doc_structure.py` 查。
- `docs/decisions.md` 和 `docs/open_questions.md` 只追加。要推翻一条决定，加一条带日期的新条目说明取代哪条、为什么；不删不改旧条目。
- 新代号（模块名、记忆层的名字、心情值的名字）在 `docs/glossary_zh.md` 加一行人话。
- 文档用中文，文件名英文小写加下划线，中文文档末尾 `_zh`；代码和注释用英文。

## 代码

- **积木化，不许写成屎山**（用户 10-29，决定 40）：照 ROS 的思路，每个模块是一个节点，只管自己的事；节点之间只传 `src/fish/msgs.py` 里的消息、只调对方 `__init__.py` 导出的东西，谁订什么写在 `src/fish/app.py`（夜里的在 `routines/nightly.py` 的 `NIGHT_STEPS`）。**加功能 = 加一块积木（一个文件）加一行接线，改一样东西 = 只改一个文件。** 一个文件开始装好几件事（超过三四百行、或一改要连带改别处），就先拆再加；拆是纯搬家，拆前拆后行为逐字节一样。`docs/nodes_design_zh.md` 是做法，`tests/test_skeleton.py` 把越界的写法拦下。
- 所有代码在 `src/fish/`，按 `docs/architecture_zh.md` 的模块放；跨模块只通过各模块 `__init__.py` 导出的接口调用。
- **大脑不认识电话线。** `brain/` 和 `memory/` 不能 import `channels/`；换终端还是换微信，大脑一行不改。
- 用户的聊天记录和鱼的记忆是私人数据，只放 `data/`（已 gitignore）。测试用临时目录，不碰 `data/`。
- **仓库是公开的**（决定 16）。跟踪的文件里不写用户的私事：住的城市、学校、真名、聊天原文、机器的地址。要举例就编一个（测试里的城市用 Springfield）。
- 密钥只从 `.env` 读（`DEEPSEEK_API_KEY`）；任何文件里不出现真密钥。
- 新模块在 `src/fish/README.md` 加一行；新脚本在 `scripts/README.md` 加一行；行为改变带测试。
- 鱼可以"犯错"，但那是**人设层故意的**（记错一个细节、懒得回长话），不是代码 bug。两者分开：bug 修掉，人设的不完美写进 `docs/persona_zh.md`。

## 要用户定的事

改人设底线、改记忆遗忘的规则、接任何外部平台（微信等）、花钱的事（API 用量、服务器），都先问用户，记到 `docs/decisions.md` 再做。
