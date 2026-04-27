#!/usr/bin/env python3
"""
context-stop.py — Stop hook: deep-context reminder.

Fires after every Claude response. If the transcript has grown past
WARN_BYTES, prints a reminder to the conversation so the user knows
to wrap up, document, and Ctrl-D.

No kill. User is in control of when the session ends.
"""
import json
import sys
from pathlib import Path

WARN_BYTES = 400_000  # ~400 KB transcript = time to start wrapping up

data = json.load(sys.stdin)

if data.get("stop_hook_active"):
    sys.exit(0)

transcript_path = data.get("transcript_path", "")
if transcript_path:
    p = Path(transcript_path)
    if p.exists() and p.stat().st_size > WARN_BYTES:
        print(
            "\n⚠️  Deep context — transcript is large. "
            "Good time to commit, update MEMORY.md, and Ctrl-D when ready."
        )

sys.exit(0)
