#!/usr/bin/env python3
"""
context-status.py — Claude Code status line: shows context window usage.

Receives a JSON blob on stdin with context_window.used_percentage.
Outputs a single JSON line: {"text": "...", "color": "..."}.

Color bands:
  green   0–69%   normal
  yellow  70–89%  getting heavy — consider /compact
  red     90%+    critical — Stop hook will end the session after next response
"""
import json
import sys

try:
    data = json.load(sys.stdin)
    ctx = data.get("context_window", {})
    used = ctx.get("used_percentage", 0)

    if used >= 90:
        text = f"⛔ {used:.0f}% — session ending after response"
        color = "red"
    elif used >= 70:
        text = f"⚠ {used:.0f}% context — /compact?"
        color = "yellow"
    else:
        text = f"◉ {used:.0f}%"
        color = "green"

    print(json.dumps({"text": text, "color": color}))

except Exception:
    print(json.dumps({"text": "◉ ctx?", "color": "gray"}))
