# 文档怎么写、放哪

> **是什么：** 每份文档的固定开头、写法、放的位置。
> **地位：** 现行（从 Yaqi 仓库的同名文件抄来做轻）。`scripts/check_doc_structure.py` 查能机械查的几条。
> **读法：** 第一次写文档前读一遍。

## 1. 为什么

每个新会话从零开始读仓库。它要**只看一份文件前几行**就知道这份文件是什么、还算不算数。

## 2. 三行卡片

标题下面紧接：

```markdown
# 标题

> **是什么：** 一句话。
> **地位：** 现行 / 账本 / 索引 / 规程 之一，再加一句以谁为准。
> **读法：** 怎么读最省事。
```

## 3. 怎么写

1. 先结论，后理由。
2. 现行文件只写现在成立的；被取代的删掉或在同一句里写"已被 X 取代"。
3. 说人话，代号放括号。
4. 一个事实只写一处：现状只在 `STATUS.md`，架构只在 `architecture_zh.md`，人设只在 `persona_zh.md`，决定只在 `decisions.md`。
5. 日期写绝对日期（`2026-10-26` 或 `10-26`）。
6. `STATUS.md` ≤ 8 KB、`AGENTS.md` ≤ 8 KB。
7. 文件名英文小写加下划线，中文文档末尾 `_zh`。

## 4. 新东西放哪

| 要写的 | 放哪 | 同一次提交还改 |
|---|---|---|
| 定下的事 | `decisions.md` 末尾一条 + 索引一行 | 术语表、`STATUS.md` |
| 没定的事 | `open_questions.md` 一节 + 索引一行 | `STATUS.md` §3 |
| 今天做了什么 | `log/YYYY-MM-DD.md`（`python3 scripts/new_log.py`） | — |
| 改人设 | `persona_zh.md` | — |
| 改模块边界 | `architecture_zh.md`，再改代码 | `src/fish/README.md` |
| 新脚本 | `scripts/` | `scripts/README.md` 一行 |

## 5. 机器查的

`scripts/check_doc_structure.py`：`docs/` 顶层每份 `.md`、每个 `README.md` 前 15 行有 `**地位：**`；`docs/README.md` 列全 `docs/` 顶层文件和文件夹；入口文件不超预算。提交钩子在改到 `docs/`、`STATUS.md`、`AGENTS.md`、`README.md` 时自动跑。
