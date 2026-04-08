# ferretlog 🐾

**`git log` for your Claude Code agent runs.**

Your agent ran for 11 minutes. What did it actually *do*? Right now: scroll. Forever.

```
$ ferretlog

  a3f2b1c9  2026-04-08 09:12  fix the authentication bug       [main]
            7 calls  2 files  3m56s  claude-opus-4-6  2,841 tok  ~$0.063

  9c1b2d3e  2026-04-07 14:33  add rate limiting to API          [main]
            9 calls  4 files  6m55s  claude-opus-4-6  3,102 tok  ~$0.071

  e4f5a6b7  2026-04-06 11:02  refactor the database layer       [main]
           10 calls  4 files 11m13s  claude-opus-4-6  4,218 tok  ~$0.094
```

`ferretlog` reads the session logs Claude Code already writes to `~/.claude/projects/` and gives you a proper CLI for your agent history. Zero config. Zero deps. Pure stdlib Python. Works on every session you've *ever* run — retroactively.

---

## Install

```bash
pip install ferretlog
```

No API keys. No daemon. No database. Just install and run.

---

## Commands

```bash
ferretlog                    # recent runs, git log style
ferretlog show <id>          # full tool-by-tool breakdown
ferretlog diff <a> <b>       # side-by-side comparison of two runs
ferretlog stats              # aggregate cost, tokens, time across all sessions
```

---

## `show` — replay any run

```
$ ferretlog show a3f2b1c9

  run      a3f2b1c9
  task     fix the authentication bug
  date     2026-04-08 09:12
  duration 3m56s
  model    claude-opus-4-6
  branch   main
  tokens   in=1,204  out=1,637  cache=84,331  ~$0.0634

  files touched:
  M  src/auth.py
  M  tests/test_auth.py

  tool calls:
  00  read    src/auth.py
  01  read    tests/test_auth.py
  02  bash    $ pytest tests/test_auth.py -x
  03  edit    src/auth.py
  04  bash    $ pytest tests/test_auth.py -x
  05  edit    tests/test_auth.py
  06  bash    $ pytest tests/ --tb=short
```

---

## `diff` — why did the same prompt go differently?

```
$ ferretlog diff a3f2b1c9 9c1b2d3e

  a3f2b1c9  fix the auth bug           │  9c1b2d3e  fix the auth bug
  09:12  7 calls  3m56s                │  14:33  9 calls  5m12s
  ────────────────────────────────────────┼────────────────────────────────────────
  tool calls
  = 00 read    src/auth.py             │  00 read    src/auth.py
  = 01 read    tests/test_auth.py      │  01 read    tests/test_auth.py
  = 02 bash    $ pytest tests/ -x      │  02 bash    $ pytest tests/ -x
  - 03 edit    src/auth.py             │
                                       │  03 bash    $ grep -r 'token' src/
  ~ 04 bash    $ pytest tests/ -x      │  04 edit    src/auth.py
                                       │  05 edit    src/config.py
  = 05 edit    tests/test_auth.py      │  06 edit    tests/test_auth.py
  = 06 bash    $ pytest tests/         │  07 bash    $ pytest tests/
  ────────────────────────────────────────┼────────────────────────────────────────
  files touched
  = src/auth.py                        │  src/auth.py
  = tests/test_auth.py                 │  tests/test_auth.py
  +                                    │  src/config.py
  ════════════════════════════════════════╪════════════════════════════════════════
  DIFFERENT
```

---

## `stats` — your agent, by the numbers

```
$ ferretlog stats 🐾

  runs           47
  tool calls     412   (avg 8/run)
  files touched  89
  total time     6h14m

  top tools:
  bash    180  ████████████████████
  read    102  ████████████
  edit     74  █████████
  write    56  ███████
```

---

## How it works

Claude Code already writes complete session logs to `~/.claude/projects/`. `ferretlog` parses the JSONL, reconstructs the tool-call sequence, and correlates each run to the nearest git commit by timestamp.

- **Local-only.** Nothing leaves your machine. No network calls, ever.
- **Zero config.** No init, no daemon, no database.
- **Zero deps.** Pure Python stdlib. Reads files. That's it.
- **Already there.** Works on every Claude Code session you've ever run.

---

## Why

You can't improve what you can't see. Agents are becoming the most expensive thing in your dev loop — and the least observable. `ferretlog` is the smallest possible step toward fixing that: take the data Claude Code is already writing to your disk, and make it `grep`-able, `diff`-able, `stat`-able.

If you've ever scrolled a 4,000-line agent transcript looking for *"wait, when did it touch that file?"* — this is for you.

---

## License

MIT. Go wild.