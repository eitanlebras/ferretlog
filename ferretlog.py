#!/usr/bin/env python3
"""
ferretlog 🐾 — git log for your AI agent runs.

Ferrets hoard everything. So does ferretlog.

Usage:
    ferretlog                        List all agent runs in this repo
    ferretlog show <id>              Full tool-by-tool breakdown of a run
    ferretlog diff <id1> <id2>       What did the agent do differently?
    ferretlog stats                  Aggregate stats across all runs
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── colors ───────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
MAGENTA = "\033[35m"


def color(c, s): return f"{c}{s}{RESET}"
def bold(s):     return color(BOLD, s)
def dim(s):      return color(DIM, s)


# ── Claude Code log schema ────────────────────────────────────────────────────
# ~/.claude/projects/<path-hash>/<session-uuid>.jsonl
# Each line is a JSON message in the conversation.
# Roles: "user" | "assistant"
# Content blocks: text | tool_use | tool_result

CLAUDE_DIR = Path.home() / ".claude" / "projects"


def _find_project_dir() -> Path | None:
    """Find the Claude Code project dir matching the current working directory."""
    cwd = str(Path.cwd())

    if not CLAUDE_DIR.exists():
        return None

    best     = None
    best_mtime = 0

    for d in CLAUDE_DIR.iterdir():
        if not d.is_dir():
            continue
        jsonl_files = list(d.glob("*.jsonl"))
        if not jsonl_files:
            continue

        # Peek at first few lines of newest file to read cwd
        newest = max(jsonl_files, key=lambda f: f.stat().st_mtime)
        try:
            with open(newest) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("cwd") == cwd:
                            mtime = newest.stat().st_mtime
                            if mtime > best_mtime:
                                best       = d
                                best_mtime = mtime
                            break
                    except Exception:
                        pass
        except Exception:
            pass

    if best:
        return best

    # Fallback: most recently modified dir
    candidates = [(d, max((f.stat().st_mtime for f in d.glob("*.jsonl")), default=0))
                  for d in CLAUDE_DIR.iterdir() if d.is_dir()]
    candidates = [(d, t) for d, t in candidates if t > 0]
    return max(candidates, key=lambda x: x[1])[0] if candidates else None


def _matches_path(dirname: str, cwd: Path) -> bool:
    """Check if a Claude project dirname corresponds to cwd."""
    # Claude Code replaces path separators with dashes or encodes them
    # Try a few known patterns
    path_str = str(cwd)
    normalized = path_str.replace("/", "-").lstrip("-")
    if normalized in dirname or dirname in normalized:
        return True
    # Hash match
    h = hashlib.md5(path_str.encode()).hexdigest()[:8]
    if h in dirname:
        return True
    return False


def _load_sessions(project_dir: Path) -> list[dict]:
    """Load and parse all JSONL session files into structured runs."""
    runs = []

    for jsonl_file in sorted(project_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime):
        try:
            run = _parse_session(jsonl_file)
            if run:
                runs.append(run)
        except Exception:
            continue

    return sorted(runs, key=lambda r: r["started_at"], reverse=True)


def _parse_session(path: Path) -> dict | None:
    """Parse a single JSONL session file into a structured run."""
    messages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not messages:
        return None

    tool_calls      = []
    files_touched   = set()
    first_user_text = None
    timestamps      = []
    model           = None
    git_branch      = None
    session_cwd     = None
    input_tokens    = 0
    output_tokens   = 0
    cache_read      = 0

    for msg in messages:
        mtype = msg.get("type", "")
        ts    = msg.get("timestamp")
        if ts:
            timestamps.append(ts)

        # Grab cwd + branch from any message
        if not session_cwd and msg.get("cwd"):
            session_cwd = msg["cwd"]
        if not git_branch and msg.get("gitBranch"):
            git_branch = msg["gitBranch"]

        # ── user messages ──────────────────────────────────────────────────
        if mtype == "user":
            content = msg.get("message", {}).get("content", "")
            if isinstance(content, str) and not first_user_text:
                first_user_text = content[:120]
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text" and not first_user_text:
                            first_user_text = block.get("text", "")[:120]

        # ── assistant messages ─────────────────────────────────────────────
        elif mtype == "assistant":
            inner = msg.get("message", {})

            # model
            if not model and inner.get("model"):
                model = inner["model"]

            # token usage
            usage = inner.get("usage", {})
            input_tokens  += usage.get("input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)
            cache_read    += usage.get("cache_read_input_tokens", 0)

            # tool calls in content
            for block in inner.get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    inp  = block.get("input", {})
                    tool_calls.append({"tool": name, "input": inp})
                    for key in ("path", "file_path", "filename"):
                        if key in inp:
                            files_touched.add(inp[key])

    if not tool_calls and not first_user_text:
        return None

    # ── timing ────────────────────────────────────────────────────────────
    def parse_ts(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    started_at = parse_ts(timestamps[0]) if timestamps else path.stat().st_mtime
    ended_at   = parse_ts(timestamps[-1]) if len(timestamps) > 1 else started_at
    if started_at is None: started_at = path.stat().st_mtime
    if ended_at   is None: ended_at   = started_at
    duration_s = max(0, ended_at - started_at)

    # ── cost estimate (input $15/M, output $75/M for opus) ────────────────
    model_lower = (model or "").lower()
    if "haiku" in model_lower:
        in_rate, out_rate = 0.80, 4.0
    elif "sonnet" in model_lower:
        in_rate, out_rate = 3.0, 15.0
    else:  # opus default
        in_rate, out_rate = 15.0, 75.0
    cost_usd = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

    return {
        "id":            path.stem,
        "short_id":      path.stem[:8],
        "task":          first_user_text or "(no task description)",
        "started_at":    started_at,
        "duration_s":    duration_s,
        "tool_calls":    tool_calls,
        "files_touched": sorted(files_touched),
        "git_ref":       _nearest_git_commit(started_at),
        "git_branch":    git_branch,
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cache_read":    cache_read,
        "cost_usd":      cost_usd,
        "cwd":           session_cwd,
        "session_file":  str(path),
    }


def _nearest_git_commit(ts: float) -> str | None:
    """Find the git commit closest to this timestamp."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H %ct %s", "-20"],
            capture_output=True, text=True, cwd=Path.cwd()
        )
        if result.returncode != 0:
            return None

        closest = None
        closest_delta = float("inf")
        for line in result.stdout.strip().splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            commit_hash, commit_ts = parts[0], parts[1]
            delta = abs(float(commit_ts) - ts)
            if delta < closest_delta:
                closest_delta = delta
                closest = commit_hash[:7]

        return closest if closest_delta < 3600 else None  # within 1 hour
    except Exception:
        return None


def _tool_counts(tool_calls: list) -> dict:
    counts = {}
    for tc in tool_calls:
        counts[tc["tool"]] = counts.get(tc["tool"], 0) + 1
    return counts


def _format_duration(s: float) -> str:
    if s < 60:
        return f"{int(s)}s"
    return f"{int(s//60)}m{int(s%60)}s"


def _format_ts(ts: float) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M")


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_log(project_dir: Path, n: int = 20, all_runs: bool = False):
    runs = _load_sessions(project_dir)
    if not runs:
        print(dim("  🐾 no runs found — has your ferret been working?"))
        return

    limit = len(runs) if all_runs else min(n, len(runs))
    runs = runs[:limit]

    print()
    for run in runs:
        counts   = _tool_counts(run["tool_calls"])
        top_tools = ", ".join(f"{t}×{c}" for t, c in
                              sorted(counts.items(), key=lambda x: -x[1])[:3])
        dur      = _format_duration(run["duration_s"]) if run["duration_s"] else "?"
        model    = dim(f"  {run['model']}") if run.get("model") else ""
        cost     = dim(f"  ~${run['cost_usd']:.3f}") if run.get("cost_usd") else ""
        tokens   = run["input_tokens"] + run["output_tokens"]
        tok_str  = dim(f"  {tokens:,} tok") if tokens else ""
        branch   = dim(f"  [{run['git_branch']}]") if run.get("git_branch") else ""

        print(f"  {color(YELLOW, run['short_id'])}  "
              f"{dim(_format_ts(run['started_at']))}  "
              f"{bold(run['task'][:60])}"
              f"{branch}")
        n_calls = len(run["tool_calls"])
        n_files = len(run["files_touched"])
        print(f"           {dim(f'{n_calls} calls  {n_files} files  {dur}')}"
              f"{model}{tok_str}{cost}  {dim(top_tools)}")
        print()


def cmd_show(project_dir: Path, run_id: str):
    runs = _load_sessions(project_dir)
    run = next((r for r in runs if r["short_id"] == run_id or r["id"].startswith(run_id)), None)

    if not run:
        print(f"  {RED}run '{run_id}' not found{RESET}")
        sys.exit(1)

    print()
    print(f"  {bold('run')}      {color(YELLOW, run['short_id'])}")
    print(f"  {bold('task')}     {run['task']}")
    print(f"  {bold('date')}     {_format_ts(run['started_at'])}")
    print(f"  {bold('duration')} {_format_duration(run['duration_s'])}")
    if run.get("model"):
        print(f"  {bold('model')}    {dim(run['model'])}")
    if run.get("git_branch"):
        print(f"  {bold('branch')}   {dim(run['git_branch'])}")
    if run.get("git_ref"):
        print(f"  {bold('commit')}   {dim(run['git_ref'])}")
    tok_in  = run.get("input_tokens", 0)
    tok_out = run.get("output_tokens", 0)
    if tok_in or tok_out:
        cost      = run.get("cost_usd", 0)
        cache_tok = run.get("cache_read", 0)
        print(f"  {bold('tokens')}   {dim(f'in={tok_in:,}  out={tok_out:,}  cache={cache_tok:,}  ~${cost:.4f}')}")
    print()

    if run["files_touched"]:
        print(f"  {bold('files touched:')}")
        for f in run["files_touched"]:
            print(f"    {GREEN}M{RESET}  {f}")
        print()

    print(f"  {bold('tool calls:')}")
    for i, tc in enumerate(run["tool_calls"]):
        inp = tc["input"]
        # Summarize input nicely
        if "command" in inp:
            detail = dim(f"  $ {inp['command'][:80]}")
        elif "path" in inp:
            detail = dim(f"  {inp['path']}")
        elif "content" in inp and isinstance(inp["content"], str):
            detail = dim(f"  {inp['content'][:60].strip()}")
        else:
            keys = list(inp.keys())[:2]
            detail = dim(f"  {', '.join(keys)}") if keys else ""

        print(f"    {DIM}{i:02d}{RESET}  {color(CYAN, tc['tool'])}{detail}")
    print()


def _strip_ansi(s: str) -> str:
    """Return visible length of a string, ignoring ANSI escape codes."""
    import re
    return re.sub(r'\x1b\[[0-9;]*m', '', s)


def _visible_len(s: str) -> int:
    return len(_strip_ansi(s))


def _pad(s: str, width: int) -> str:
    """Pad a string to visible width, accounting for ANSI codes."""
    return s + " " * max(0, width - _visible_len(s))


def _tool_detail(tc: dict) -> str:
    """One-line summary of a tool call's input."""
    inp = tc.get("input", {})
    if "command" in inp:
        return dim(f"$ {inp['command'][:35]}")
    elif "path" in inp:
        return dim(inp["path"][:38])
    elif "content" in inp and isinstance(inp["content"], str):
        return dim(inp["content"][:38].strip())
    return ""


def _lcs(a: list, b: list) -> list:
    """Longest common subsequence — returns list of (ia, ib) matched index pairs."""
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i+1][j+1] + 1
            else:
                dp[i][j] = max(dp[i+1][j], dp[i][j+1])
    pairs = []
    i = j = 0
    while i < m and j < n:
        if a[i] == b[j]:
            pairs.append((i, j)); i += 1; j += 1
        elif dp[i+1][j] >= dp[i][j+1]:
            i += 1
        else:
            j += 1
    return pairs


def cmd_diff(project_dir: Path, id1: str, id2: str):
    runs = _load_sessions(project_dir)

    def find(rid):
        return next((r for r in runs if r["short_id"] == rid or r["id"].startswith(rid)), None)

    a, b = find(id1), find(id2)
    if not a:
        print(f"  {RED}run '{id1}' not found{RESET}"); sys.exit(1)
    if not b:
        print(f"  {RED}run '{id2}' not found{RESET}"); sys.exit(1)

    COL = 46   # visible width of each side
    SEP = f"  {dim('│')}  "

    def rule(ch="─"):
        mid = "╪" if ch == "═" else "┼"
        line = ch * COL
        return f"  {dim(line + mid + line)}"

    # ── header ────────────────────────────────────────────────────────────────
    print()
    a_hdr = f"{color(YELLOW, a['short_id'])}  {bold(a['task'][:34])}"
    b_hdr = f"{color(YELLOW, b['short_id'])}  {bold(b['task'][:34])}"
    print(f"  {_pad(a_hdr, COL)}{SEP}{b_hdr}")

    a_sub = dim(f"{_format_ts(a['started_at'])}  {_format_duration(a['duration_s'])}  {len(a['tool_calls'])} calls")
    b_sub = dim(f"{_format_ts(b['started_at'])}  {_format_duration(b['duration_s'])}  {len(b['tool_calls'])} calls")
    print(f"  {_pad(a_sub, COL)}{SEP}{b_sub}")
    print(rule())

    # ── tool sequence via LCS alignment ───────────────────────────────────────
    a_tools = a["tool_calls"]
    b_tools = b["tool_calls"]
    a_names = [t["tool"] for t in a_tools]
    b_names = [t["tool"] for t in b_tools]

    matched = _lcs(a_names, b_names)
    matched_a = {ia for ia, _ in matched}
    matched_b = {ib for _, ib in matched}

    # Build alignment rows: (a_idx_or_None, b_idx_or_None, kind)
    rows = []
    ia = ib = 0
    mi = 0
    while ia < len(a_tools) or ib < len(b_tools):
        if mi < len(matched) and matched[mi] == (ia, ib):
            rows.append((ia, ib, "match"))
            ia += 1; ib += 1; mi += 1
        elif ia < len(a_tools) and ia not in matched_a:
            rows.append((ia, None, "del"))
            ia += 1
        elif ib < len(b_tools) and ib not in matched_b:
            rows.append((None, ib, "add"))
            ib += 1
        else:
            if ia < len(a_tools): ia += 1
            if ib < len(b_tools): ib += 1

    drifted = any(k != "match" for _, _, k in rows)

    print(f"  {dim('tool calls'):}")
    for a_idx, b_idx, kind in rows:
        if kind == "match":
            tc_a = a_tools[a_idx]
            tc_b = b_tools[b_idx]
            same_input = (json.dumps(tc_a["input"], sort_keys=True) ==
                          json.dumps(tc_b["input"], sort_keys=True))
            sym   = color(GREEN, "=") if same_input else color(YELLOW, "~")
            a_col = f"{dim(f'{a_idx:02d}')} {color(CYAN, tc_a['tool'])} {_tool_detail(tc_a)}"
            b_col = f"{dim(f'{b_idx:02d}')} {color(CYAN, tc_b['tool'])} {_tool_detail(tc_b)}"
            if not same_input:
                drifted = True
        elif kind == "del":
            sym   = color(RED, "-")
            tc_a  = a_tools[a_idx]
            a_col = f"{color(RED, f'{a_idx:02d}')} {color(RED, tc_a['tool'])} {_tool_detail(tc_a)}"
            b_col = ""
            print(f"  {sym} {_pad(a_col, COL - 2)}{SEP}{b_col}")
        else:
            tc_b  = b_tools[b_idx]
            a_col = ""
            b_col = f"{color(GREEN, f'{b_idx:02d}')} {color(GREEN, tc_b['tool'])} {_tool_detail(tc_b)}"
            print(f"    {_pad(a_col, COL - 2)}{SEP}{b_col}")

    # ── files ─────────────────────────────────────────────────────────────────
    print(rule())
    print(f"  {dim('files touched'):}")

    a_files = set(a["files_touched"])
    b_files = set(b["files_touched"])
    all_files = sorted(a_files | b_files)

    for f in all_files:
        in_a = f in a_files
        in_b = f in b_files
        if in_a and in_b:
            sym = color(GREEN, "=")
            print(f"  {sym} {_pad(dim(f), COL - 2)}{SEP}{dim(f)}")
        elif in_a:
            sym = color(RED, "-")
            print(f"  {sym} {_pad(color(RED, f), COL - 2)}{SEP}")
            drifted = True
        else:
            print(f"    {_pad('', COL - 2)}{SEP}{color(GREEN, f)}")
            drifted = True

    # ── verdict ───────────────────────────────────────────────────────────────
    print(rule("═"))
    verdict = f"  {RED}{BOLD}DIFFERENT{RESET}" if drifted else f"  {GREEN}{BOLD}IDENTICAL{RESET}"
    print(verdict)
    print()


def cmd_stats(project_dir: Path):
    runs = _load_sessions(project_dir)
    if not runs:
        print(dim("  🐾 no runs found — has your ferret been working?")); return

    total_tools = sum(len(r["tool_calls"]) for r in runs)
    total_files = sum(len(r["files_touched"]) for r in runs)
    total_dur   = sum(r["duration_s"] for r in runs)

    # Tool frequency
    freq = {}
    for r in runs:
        for tc in r["tool_calls"]:
            freq[tc["tool"]] = freq.get(tc["tool"], 0) + 1

    print()
    print(f"  {bold('ferretlog 🐾 stats')}")
    print()
    print(f"  {bold('runs')}         {len(runs)}")
    print(f"  {bold('tool calls')}   {total_tools}  (avg {total_tools//max(len(runs),1)}/run)")
    print(f"  {bold('files touched')} {total_files}")
    print(f"  {bold('total time')}   {_format_duration(total_dur)}")
    print()
    print(f"  {bold('top tools:')}")
    for tool, count in sorted(freq.items(), key=lambda x: -x[1])[:8]:
        bar = "█" * min(count, 30)
        print(f"    {color(CYAN, tool):<20} {count:>4}  {dim(bar)}")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def _find_or_die() -> Path:
    project_dir = _find_project_dir()
    if not project_dir:
        # Try all projects if we can't match to current repo
        if CLAUDE_DIR.exists():
            dirs = [d for d in CLAUDE_DIR.iterdir() if d.is_dir()]
            if dirs:
                # Use most recently modified
                project_dir = max(dirs, key=lambda d: d.stat().st_mtime)

    if not project_dir or not project_dir.exists():
        print(f"\n  {RED}🐾 ferret can't find your Claude Code stash{RESET}")
        print(f"  {dim('expected logs at ~/.claude/projects/')}")
        print(f"  {dim('run claude in this repo first, then ferretlog will find it')}\n")
        sys.exit(1)

    return project_dir


def main():
    parser = argparse.ArgumentParser(
        prog="ferretlog",
        description="git log for your AI agent runs — but make it ferret",
    )
    sub = parser.add_subparsers(dest="command")

    p_log = sub.add_parser("log", help="List runs (default)")
    p_log.add_argument("-n", type=int, default=20)
    p_log.add_argument("--all", action="store_true")

    p_show = sub.add_parser("show", help="Show a run in full")
    p_show.add_argument("id")

    p_diff = sub.add_parser("diff", help="Diff two runs")
    p_diff.add_argument("a")
    p_diff.add_argument("b")

    sub.add_parser("stats", help="Aggregate stats")

    args = parser.parse_args()
    project_dir = _find_or_die()

    if args.command == "show":
        cmd_show(project_dir, args.id)
    elif args.command == "diff":
        cmd_diff(project_dir, args.a, args.b)
    elif args.command == "stats":
        cmd_stats(project_dir)
    else:
        # default: log
        n = getattr(args, "n", 20)
        all_runs = getattr(args, "all", False)
        cmd_log(project_dir, n=n, all_runs=all_runs)


if __name__ == "__main__":
    main()