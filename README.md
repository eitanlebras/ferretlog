# ferretlog 🐾

**`git log` for your Claude Code agent runs.**

Your agent ran for 11 minutes. What did it actually *do*? Right now: scroll. Forever.

`ferretlog` turns Claude Code's session history into a queryable, git-style log — zero config, zero deps, pure stdlib Python.

```
$ ferretlog

  6fcbac30  2026-04-08 12:27  write changelog for v2.1 release
             3 calls   1 file   1m27s   bash×1, read×1, write×1

  e045f8c8  2026-04-08 09:27  refactor the database layer to use async
            10 calls   4 files 11m13s   bash×3, edit×3, read×2

  3f201ab7  2026-04-07 13:27  add rate limiting to the API endpoints
             9 calls   4 files  6m55s   bash×3, read×2, write×2

  21180c86  2026-04-06 13:27  fix the authentication bug in login flow
             7 calls   2 files  3m56s   bash×3, read×2, edit×1
```

`git log` proved that structured history + a sharp CLI is transformative. Nobody's done it for agent runs. Until now.

Ferrets hoard everything. So does ferretlog.

---

## Install

```bash
pip install ferretlog     # one command. no config. no API keys.
```

## The four commands

```bash
ferretlog                         # recent runs, git log style
ferretlog show <id>               # tool-by-tool replay of a single run
ferretlog diff <a> <b>            # what changed between two runs?
ferretlog stats                   # aggregate stats across every run
```

## `show` — replay any run

```
$ ferretlog show e045f8c8

  run      e045f8c8
  task     refactor the database layer to use async
  date     2026-04-08 09:27
  duration 11m13s
  git      a3f2b1c

  files touched:
  M  src/db.py
  M  src/db_async.py
  M  src/models.py
  M  src/api.py

  tool calls:
  00  read    src/db.py
  01  read    src/models.py
  02  bash    $ grep -r 'db.session' src/
  03  write   src/db_async.py
  04  edit    src/models.py
  ...
```

## `diff` — why did the same prompt go differently?

```
$ ferretlog diff 3f201ab7 e045f8c8

  tool sequence:
  =  00  read
  =  01  read
  ~  05  write → edit
  +  09  write  (only in B)

  files:
  =  src/api.py
  -  requirements.txt   (only in A)
  +  src/db_async.py    (only in B)

  DIFFERENT
```

## `stats` — your agent, by the numbers

```
$ ferretlog stats

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

## How it works

Claude Code already writes complete session logs to `~/.claude/projects/`. `ferretlog` parses the JSONL, reconstructs the tool-call sequence, and correlates each run to the nearest git commit by timestamp.

- **Local-only.** Nothing leaves your machine. No network calls, ever.
- **Zero config.** No init, no daemon, no database.
- **Zero deps.** Pure Python stdlib. Reads files. That's it.
- **Already there.** Works on every Claude Code session you've *ever* run.

## Why

You can't improve what you can't see. Agents are becoming the most expensive thing in your dev loop — and the least observable. `ferretlog` is the smallest possible step toward fixing that: take the data Claude Code is *already* writing to your disk, and make it `grep`-able, `diff`-able, `stat`-able.

If you've ever scrolled a 4,000-line agent transcript looking for "wait, when did it touch that file?" — this is for you.

## License

MIT. Go wild.
