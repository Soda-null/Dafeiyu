"""Trial run of memory v2 (docs/memory_v2_zh.md): project forgetting under the old rule and
the new one for a dump of her real memories. Asks DeepSeek once to label each memory
(arousal, what it is about, related groups) and caches the labels. Writes nothing to data/.

Dump her memories on the box (see docs/box_zh.md), then:
  .venv/bin/python scripts/memory_v2_trial.py her_memories.json .env labels_cache.json [标签,标签]
The last argument is the tags he keeps bringing up in scenario B (default 学校,食堂).
"""
from __future__ import annotations

import json
import math
import sys
from itertools import combinations
from pathlib import Path


# ---------------- the new rule's numbers ----------------
BASE_DAYS = 4.0                      # a passing thing, unmoved: fades in days
AROUSAL_GAIN = 3.0                   # S0 *= 1 + 3*arousal  (arousal 1 -> x4)
ABOUT = {"路过": 1.0, "日常": 3.0, "本人": 40.0}  # 一辈子 -> pinned; her own things use the same ruler
INSIGHT_PROBATION_DAYS = 7.0         # an insight from < 3 days of evidence starts here
RECALL_GAIN = 1.5
SPREAD = 0.3                         # a neighbour gets this share of a recall's boost, times link weight
LINK_W = {"episode": 0.3, "tag": 0.5, "text": 0.4, "model": 0.7}
OLD_BASE = 2.1

def old_s0(m):
    if m["importance"] >= 10: return math.inf
    s = OLD_BASE ** m["importance"]
    if abs(m["valence"]) >= 0.6: s *= 1.5
    return s

def new_s0(m, lab):
    if lab["about"] == "一辈子": return math.inf
    if m["kind"] in ("insight", "howto") and lab.get("evidence_days", 1) < 3:
        return INSIGHT_PROBATION_DAYS
    return BASE_DAYS * (1 + AROUSAL_GAIN * lab["arousal"]) * ABOUT.get(lab["about"], 3.0)

def R(s, t): return 1.0 if s == math.inf else math.exp(-t / s)
def days_until(s, r): return math.inf if s == math.inf else -s * math.log(r)
def after_recall(s, r): return s if s == math.inf else s * (1 + RECALL_GAIN * (1 - r))

def bigrams(t):
    c = [x for x in t if x.isalnum() and not x.isdigit()]  # dates link nothing
    return {a + b for a, b in zip(c, c[1:])}
def sim(a, b):
    x, y = bigrams(a), bigrams(b)
    return 2 * len(x & y) / (len(x) + len(y)) if x and y else 0.0

def fmt(d):
    if d == math.inf: return "永远"
    if d >= 365: return f"{d/365:.1f} 年"
    return f"{d:.0f} 天"

# ---------------- labels from the model ----------------
PROMPT = """下面是一条 AI 朋友（大肥鱼）小本本里记的事，第三人称"他"指她的主人。请给每一条打三个标签，只输出一个 JSON 对象（json）：
{"labels": [{"id": 编号, "arousal": 0到1的小数, "about": "路过 / 日常 / 本人 / 一辈子 之一", "evidence_days": 整数}], "groups": [{"why": "一句话", "ids": [编号, 编号]}]}

- arousal：记下这一刻，他或她有多被触动（激动、感动、焦虑、生气、特别开心）。0 = 完全平淡，1 = 一辈子忘不了的那种。注意是"多触动"，不是"多重要"。
- about：这条说的是什么。路过 = 一件路过的小事（吃了什么、正在干嘛、今天的安排）；日常 = 他的近况、计划、一次性的事；本人 = 他本人长期不变的事（学校、专业、家人、长期喜好、长期状态）；一辈子 = 生日、纪念日、双方的承诺、名字这类一辈子的事。她自己的事和网上看到的也按同样尺子打。
- evidence_days：这条如果是 insight 或 howto（规律、相处方式），它背后的证据跨了几天；别的条填 1。
- groups：把说的是同一件事或同一个话题的条目分组（比如都是鱼缸的、都是学校和食堂的、都是承诺的），每组至少 2 条，一条可以在多组里。

条目：
{items}"""

def label(memories, env_path, cache):
    if cache.exists():
        return json.loads(cache.read_text())
    key = next(l.split("=", 1)[1].strip() for l in Path(env_path).read_text().splitlines()
               if l.startswith("DEEPSEEK_API_KEY="))
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com", timeout=120)
    items = "\n".join(f"[#{m['id']}] ({m['kind']}) {m['text']}" for m in memories)
    resp = client.chat.completions.create(
        model="deepseek-chat", temperature=0.2, max_tokens=4000,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": PROMPT.replace("{items}", items)}])
    data = json.loads(resp.choices[0].message.content)
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data

# ---------------- main ----------------
def main():
    dump = json.loads(Path(sys.argv[1]).read_text())
    mems = dump["memories"]
    cache = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("labels_cache.json")
    data = label(mems, sys.argv[2], cache)
    labels = {l["id"]: l for l in data["labels"]}
    by_id = {m["id"]: m for m in mems}

    # links
    links: dict[frozenset, float] = {}
    def link(a, b, w):
        k = frozenset((a, b))
        links[k] = max(links.get(k, 0.0), w)
    for a, b in combinations(mems, 2):
        if a["source_episode"] and a["source_episode"] == b["source_episode"]:
            link(a["id"], b["id"], LINK_W["episode"])
        if set(a["tags"]) & set(b["tags"]):
            link(a["id"], b["id"], LINK_W["tag"])
        if sim(a["text"], b["text"]) >= 0.25:
            link(a["id"], b["id"], LINK_W["text"])
    for g in data.get("groups", []):
        for a, b in combinations([i for i in g["ids"] if i in by_id], 2):
            link(a, b, LINK_W["model"])
    neighbours: dict[int, list[tuple[int, float]]] = {m["id"]: [] for m in mems}
    for k, w in links.items():
        a, b = tuple(k)
        neighbours[a].append((b, w)); neighbours[b].append((a, w))

    # scenario A: never mentioned again, from a fresh S0
    print("== 情景 A：记下之后再也不提 ==")
    print(f"{'#':>3} {'种类':5} {'旧分':>3} {'触动':>4} {'说的是':4} {'连':>2} | {'旧：模糊/想不起':18} | {'新：模糊/想不起':18} | 内容")
    rows = []
    for m in mems:
        lab = labels.get(m["id"], {"arousal": 0.2, "about": "日常", "evidence_days": 1})
        so, sn = old_s0(m), new_s0(m, lab)
        flag = ""
        if sn == math.inf: flag = "【钉住】"
        elif m["kind"] in ("insight", "howto") and lab.get("evidence_days", 1) < 3: flag = "【待印证】"
        rows.append((m, lab, so, sn, flag))
        print(f"{m['id']:>3} {m['kind']:5} {m['importance']:>3} {lab['arousal']:>4.1f} {lab['about']:4} {len(neighbours[m['id']]):>2} | "
              f"{fmt(days_until(so, .5)):>7} / {fmt(days_until(so, .1)):<8} | "
              f"{fmt(days_until(sn, .5)):>7} / {fmt(days_until(sn, .1)):<8} | {flag}{m['text'][:34]}")

    def count(sfun, days):
        out = []
        for d in days:
            rs = [R(sfun(r), d) for r in rows if r[0]["kind"] != "world"]
            out.append((sum(x >= .5 for x in rs), sum(.1 <= x < .5 for x in rs), sum(x < .1 for x in rs)))
        return out
    days = (7, 30, 90, 365)
    print("\n不含见闻的 %d 条，几天后 清楚/模糊/想不起：" % sum(r[0]["kind"] != "world" for r in rows))
    for name, f in (("旧规则", lambda r: r[2]), ("新规则", lambda r: r[3])):
        print(f"  {name}: " + "  ".join(f"{d}天 {a}/{b}/{c}" for d, (a, b, c) in zip(days, count(f, days))))

    # scenario B: for 90 days he brings up school/food once a week, nothing else
    print("\n== 情景 B：接下来 90 天他每周提一次学校和食堂，别的都不提 ==")
    cue_tags = set((sys.argv[4] if len(sys.argv) > 4 else "学校,食堂").split(","))  # what he keeps bringing up
    cue_ids = {m["id"] for m in mems if cue_tags & set(m["tags"])}
    print("每周直接想起的：", sorted(cue_ids))
    def simulate(spread: bool, sfun):
        s = {r[0]["id"]: sfun(r) for r in rows}
        last = {i: 0.0 for i in s}
        for day in range(7, 91, 7):
            boosted = {}
            for i in cue_ids:
                r = R(s[i], day - last[i]); boosted[i] = after_recall(s[i], r); last[i] = day
                if spread:
                    for j, w in neighbours[i]:
                        if j in cue_ids: continue
                        rj = R(s[j], day - last[j])
                        if rj < 0.02: continue  # too far gone to be touched
                        gain = 1 + SPREAD * w * RECALL_GAIN * (1 - rj)
                        boosted[j] = max(boosted.get(j, 0), s[j] * gain)  # firmer, but the clock keeps running
            s.update(boosted)
        return {i: R(s[i], 90 - last[i]) for i in s}
    old_b = simulate(False, lambda r: r[2])
    new_b = simulate(True, lambda r: r[3])
    print(f"{'#':>3} | {'旧 90天':>7} | {'新 90天':>7} | 内容")
    for m, lab, so, sn, flag in rows:
        if m["kind"] == "world": continue
        def w(x): return "清楚" if x >= .5 else ("模糊" if x >= .1 else "想不起")
        mark = " ←直接" if m["id"] in cue_ids else (" ←顺带" if any(j in cue_ids for j, _ in neighbours[m["id"]]) else "")
        print(f"{m['id']:>3} | {w(old_b[m['id']]):>6} | {w(new_b[m['id']]):>6} | {flag}{m['text'][:30]}{mark}")

    print("\n== 模型分的组（夜里会并成一条大意的候选）==")
    for g in data.get("groups", []):
        print(f"- {g['why']}: {g['ids']}")

if __name__ == "__main__":
    main()
