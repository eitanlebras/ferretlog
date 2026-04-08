#!/usr/bin/env python3
"""
Generate fake Claude Code JSONL sessions for testing agentlog.
Run this once to populate ~/.claude/projects/test-repo/
"""
import json
import os
import time
import uuid
from pathlib import Path

PROJECT_DIR = Path.home() / ".claude" / "projects" / "test-agentlog-repo"
PROJECT_DIR.mkdir(parents=True, exist_ok=True)

SESSIONS = [
    {
        "task": "fix the authentication bug in login flow",
        "offset_hours": 48,
        "duration": 240,
        "tools": [
            ("read_file",  {"path": "src/auth.py"}),
            ("read_file",  {"path": "tests/test_auth.py"}),
            ("bash",       {"command": "pytest tests/test_auth.py -x"}),
            ("str_replace",{"path": "src/auth.py", "content": "fixed token validation"}),
            ("bash",       {"command": "pytest tests/test_auth.py -x"}),
            ("write_file", {"path": "tests/test_auth.py", "content": "added edge case tests"}),
            ("bash",       {"command": "pytest tests/ --tb=short"}),
        ],
    },
    {
        "task": "add rate limiting to the API endpoints",
        "offset_hours": 24,
        "duration": 420,
        "tools": [
            ("read_file",  {"path": "src/api.py"}),
            ("read_file",  {"path": "requirements.txt"}),
            ("bash",       {"command": "pip install slowapi"}),
            ("write_file", {"path": "src/middleware/rate_limit.py", "content": "rate limiter impl"}),
            ("str_replace",{"path": "src/api.py", "content": "added limiter decorator"}),
            ("write_file", {"path": "tests/test_rate_limit.py", "content": "rate limit tests"}),
            ("bash",       {"command": "pytest tests/test_rate_limit.py"}),
            ("bash",       {"command": "pytest tests/"}),
            ("str_replace",{"path": "requirements.txt", "content": "slowapi==0.1.9"}),
        ],
    },
    {
        "task": "refactor the database layer to use async",
        "offset_hours": 4,
        "duration": 680,
        "tools": [
            ("read_file",  {"path": "src/db.py"}),
            ("read_file",  {"path": "src/models.py"}),
            ("bash",       {"command": "grep -r 'db.session' src/"}),
            ("write_file", {"path": "src/db_async.py", "content": "async db layer"}),
            ("str_replace",{"path": "src/models.py", "content": "async model methods"}),
            ("str_replace",{"path": "src/api.py", "content": "await db calls"}),
            ("bash",       {"command": "python -m pytest tests/ -x --asyncio-mode=auto"}),
            ("str_replace",{"path": "src/db_async.py", "content": "fix connection pooling"}),
            ("bash",       {"command": "python -m pytest tests/ --asyncio-mode=auto"}),
            ("write_file", {"path": "src/db.py", "content": "deprecated, use db_async"}),
        ],
    },
    {
        "task": "write changelog for v2.1 release",
        "offset_hours": 1,
        "duration": 90,
        "tools": [
            ("bash",       {"command": "git log v2.0..HEAD --oneline"}),
            ("read_file",  {"path": "CHANGELOG.md"}),
            ("write_file", {"path": "CHANGELOG.md", "content": "## v2.1.0 ..."}),
        ],
    },
]


def make_session(s: dict) -> Path:
    session_id = str(uuid.uuid4())
    path = PROJECT_DIR / f"{session_id}.jsonl"
    now = time.time()
    start_ts = now - (s["offset_hours"] * 3600)
    step = s["duration"] / max(len(s["tools"]), 1)

    lines = []

    # First user message
    lines.append(json.dumps({
        "role": "user",
        "content": s["task"],
        "timestamp": _iso(start_ts),
    }))

    # Assistant + tool calls
    for i, (tool, inp) in enumerate(s["tools"]):
        ts = start_ts + (i * step)
        tool_id = f"tool_{uuid.uuid4().hex[:8]}"

        lines.append(json.dumps({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tool_id, "name": tool, "input": inp}],
            "timestamp": _iso(ts),
        }))
        lines.append(json.dumps({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}],
            "timestamp": _iso(ts + step * 0.9),
        }))

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return path


def _iso(ts: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    print(f"Writing test sessions to {PROJECT_DIR}")
    for s in SESSIONS:
        p = make_session(s)
        print(f"  ✓ {p.name[:16]}...  '{s['task'][:50]}'")
    print(f"\nDone. Now run:\n  python agentlog.py\n  python agentlog.py stats")
