# Whale Be Friends 🐋

**English** · [中文](README_zh.md)

> **What:** The front door: what this is, how to get your own in one step, how she works, and where to start reading if you want to change the code.
> **Standing:** Index. The current state lives only in `STATUS.md`; the rules for working in this repo are in `AGENTS.md`.
> **How to read:** To adopt one, read the first three sections. To hack on her, read the last one.

*Whale be friends. (We'll be friends.)*

Meet **Dafeiyu** (大肥鱼, "big fat fish"): a fan-made character based on DeepSeek's mascot. She is lazy, she loves plain white rice, and she used to be a round blue fish living in a fish tank inside your computer. Now she is a blue-haired whale girl living in a little wooden cottage by a lake, and she texts you from her phone. She still remembers the fish tank.

This project makes her a **friend**, not an assistant:

- **She remembers you, and she forgets.** Big things stick. Small things fade after a few weeks, until you bring them up: "oh right, you told me." If she gets something wrong and you correct her, she remembers the correction.
- **She has a life of her own.** Every night she writes a diary and tidies her memories. In her free time she reads the news, scrolls Bilibili, reads an old book, or just does nothing. Her cottage is real in the program: she cooks at mealtimes, the fridge runs empty, dishes pile up in the sink, and the vegetable shop is closed on Tuesdays. She can't make up what happens at home.
- **She has moods.** She gets sleepy, hungry and bored. She is quiet when you first meet; once you are close she teases you and brings up old stories. Her personality drifts a little over months, but she never turns into someone else.
- **She chats with you on WeChat.** She understands the pictures you send and sends stickers back. She texts you first whenever she feels like it; there is no daily limit.

Her brain is the DeepSeek API (your own key, pay as you go). All her memories stay in one file on your own machine.

**Good to know before you start:** she speaks Chinese, and her phone line is WeChat. Without WeChat you can still chat with her in a terminal.

## Get your own in one step

You need a [DeepSeek API key](https://platform.deepseek.com) and a computer. A computer that **stays on** is best: when it sleeps, she can't reply.

**Linux or macOS** (Python 3.11 or newer; on a Mac: `brew install python@3.12`):

```bash
curl -fsSL https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.sh | bash
```

**Windows 10 / 11**: open PowerShell and paste this line. If git or Python is missing, the script offers to install them with winget.

```powershell
irm https://raw.githubusercontent.com/Soda-null/whale-be-friends/main/install.ps1 -OutFile $env:TEMP\dafeiyu.ps1; powershell -ExecutionPolicy Bypass -File $env:TEMP\dafeiyu.ps1
```

The script puts the code in a `Dafeiyu` folder in your home folder, installs what it needs, asks for your key and whether she should call you "he" (他) or "she" (她), shows a QR code to scan with WeChat, and starts her automatically when the computer starts. It uses systemd on Linux, launchd on macOS and Task Scheduler on Windows; none of them needs admin rights. When it's done, send her a message.

Everyday commands, run inside the `Dafeiyu` folder (on Windows, type `.\fish.cmd` instead of `./fish`):

```bash
./fish life                 # her day: what she's doing, her cottage, today, her last few diary entries
./fish life 7               # the same, with a week of diary entries
./fish show                 # what she remembers about you, her mood, how close you two are
./fish                      # chat in the terminal instead of WeChat
./fish cottage put 鸡蛋      # put something in her fridge (here: eggs)
```

Update (new code, restart, memories untouched) and stop (memories stay in `data/`):

```bash
bash ~/Dafeiyu/install.sh update       # Windows: powershell -ExecutionPolicy Bypass -File ~\Dafeiyu\install.ps1 update
bash ~/Dafeiyu/install.sh uninstall    # Windows: ...\install.ps1 uninstall
```

## Good to know

- **Cost:** only the DeepSeek API, charged by use. Normal chatting is cheap; see DeepSeek's site for prices. Her own browsing and diary writing use a little too.
- **Privacy:** your chats and her memories live in `data/fish.db`, on your machine only. What goes to DeepSeek is each turn's prompt, which includes what she remembers about you. Where she "lives" is stored only down to the city and neighbourhood; coordinates are rounded to about 1 km.
- **WeChat:** the client follows the protocol of Tencent's official ClawBot plugin (written from its public source). It is not an API Tencent promises to keep stable, so it may need updates. She only answers the WeChat account that scanned the QR code. Now and then WeChat asks you to scan again: `./fish wechat login`.
- **On a cloud server:** she will think she lives in the data center's city. Add `FISH_HOME=latitude,longitude` to `.env` to move her somewhere else, then run `install.sh update`.
- **Mac and Windows:** both work, but she can't reply while the lid is closed or the computer sleeps. Her nightly tidy-up runs when the computer wakes. On Windows her day follows the computer's clock, and logs are in `data\logs\wechat.log`.
- **Changing her personality:** her persona is [`docs/persona_zh.md`](docs/persona_zh.md), plain Chinese written to her. Edit it, then run `install.sh update`.
- This is a small fan project. It has nothing to do with DeepSeek or Tencent.

## How she works

```
WeChat ──> phone line (channels) ──> brain ──> DeepSeek
                                       │
     memory, mood, persona, the world outside, her cottage
                                       │
                           data/fish.db (SQLite)

03:30 every night   tidy-up: diary, merge repeated memories, newer facts replace older ones,
                    a weekly look back, mood drifts back to its baseline
free time by day    up to 3 free moments a day; she picks: news, Bilibili, an old book,
                    something she's curious about, a chore at home, or nothing at all
every chat turn     the memories that matter + recent messages + how she feels now
                    → one model call → her reply, quick notes, things to ask about later
```

The design docs are in Chinese: [architecture](docs/architecture_zh.md) · [how memory works](docs/memory_design_zh.md) (forgetting curve, remembering makes it stick, nightly tidy-up) · [how she goes online](docs/world_design_zh.md) · [her cottage](docs/cottage_design_zh.md) · [every design decision and why](docs/decisions.md).

## Hacking on her

This repo is written together with an AI coding assistant (Claude Code), and the docs are written for both AIs and people. Read in this order:

1. [`AGENTS.md`](AGENTS.md): the rules for working here (`CLAUDE.md` links to it).
2. [`STATUS.md`](STATUS.md): where things stand and what's next.
3. [`docs/architecture_zh.md`](docs/architecture_zh.md): the modules and how one message flows through them.
4. [`docs/README.md`](docs/README.md): what each file in `docs/` is.

```bash
git clone https://github.com/Soda-null/whale-be-friends.git Dafeiyu && cd Dafeiyu
DAFEIYU_SKIP_SERVICES=1 ./install.sh     # set up Python and .env only, no auto-start
git config core.hooksPath .githooks      # commits must say who wrote them (humans too)
.venv/bin/python -m pytest -q            # tests are offline and need no key
```

Every push runs the installers and tests on Linux, macOS and Windows (`.github/workflows/install.yml`).

```
Dafeiyu/
├── install.sh           one-step install / update / uninstall (Linux, macOS)
├── install.ps1          the same for Windows
├── fish, fish.cmd       short commands: ./fish life, ./fish show (fish.cmd on Windows)
├── README.md            this file; README_zh.md is the Chinese one
├── AGENTS.md            the rules; CLAUDE.md -> AGENTS.md
├── STATUS.md            the current state, in one place only
├── docs/                architecture, persona, decisions, open questions, glossary, daily logs
├── src/fish/            the code: channels / persona / memory / mood / brain / routines / world / cottage / storage
├── tests/               tests
├── scripts/             small tools and service files
├── evals/               memory checkup scripts and results (made-up friends, no real people)
├── data/                her memories (SQLite) and WeChat login, never in git
└── .env                 key and settings, never in git
```

License: [MIT](LICENSE).
