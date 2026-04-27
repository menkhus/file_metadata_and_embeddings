#!/usr/bin/env python3
"""
test_prompt_ground.py — Unit tests for prompt-ground.py scoring and state logic.

Tests:
  - score_node: pool weighting, recency, staleness penalty
  - min_score_for_turn: focus-narrowing formula
  - _load_state / _save_state: round-trip persistence
  - main(): end-to-end via subprocess with mocked DB/LLM
"""

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Load the module under test without executing its if __name__ == "__main__"
# block and without triggering external imports at module level.
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parent / "prompt-ground.py"


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("prompt_ground", _SCRIPT)
    mod  = importlib.util.module_from_spec(spec)
    # Patch sys before executing the module body so it doesn't collide with
    # the test runner's own sys.argv / sys.stdin.
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()
score_node        = _mod.score_node
min_score_for_turn = _mod.min_score_for_turn
_load_state       = _mod._load_state
_save_state       = _mod._save_state
_seen_file        = _mod._seen_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(a=0, b=0, last_turn=0, shown=0, last_shown=0) -> dict:
    return {
        "a_count": a,
        "b_count": b,
        "last_turn": last_turn,
        "shown_count": shown,
        "last_shown": last_shown,
    }


# ---------------------------------------------------------------------------
# score_node — pool weighting
# ---------------------------------------------------------------------------

def test_pool_ab_beats_a_only():
    """A+B confirmed node scores higher than A-only with same frequency."""
    ab = _entry(a=1, b=1, last_turn=1)     # pool_weight=3, freq=2
    a_only = _entry(a=2, b=0, last_turn=1)  # pool_weight=2, freq=2
    assert score_node(ab, 1) > score_node(a_only, 1)


def test_a_only_beats_b_only():
    b_only = _entry(a=0, b=2, last_turn=1)
    a_only = _entry(a=2, b=0, last_turn=1)
    assert score_node(a_only, 1) > score_node(b_only, 1)


def test_zero_matches_zero_score():
    """Entry with no matches should score zero."""
    assert score_node(_entry(), 1) == 0.0


# ---------------------------------------------------------------------------
# score_node — recency decay
# ---------------------------------------------------------------------------

def test_recency_decays_with_turn_gap():
    """Node matched last turn scores higher than node matched 5 turns ago."""
    fresh = _entry(a=1, last_turn=9)
    stale = _entry(a=1, last_turn=5)
    assert score_node(fresh, 10) > score_node(stale, 10)


def test_recency_at_same_turn():
    """Node matched on the current turn has recency = 1.0 (maximum)."""
    e = _entry(a=1, last_turn=5)
    assert score_node(e, 5) == score_node(_entry(a=1, last_turn=1), 1)


# ---------------------------------------------------------------------------
# score_node — staleness / injection feedback loop
# ---------------------------------------------------------------------------

def test_staleness_ratio_half():
    """shown=4, frequency=2 → staleness=0.5 → score is half of unshown equivalent."""
    clean   = _entry(a=1, b=1, last_turn=1, shown=0)
    stale   = _entry(a=1, b=1, last_turn=1, shown=4)
    # staleness for stale = 2/4 = 0.5
    assert abs(score_node(stale, 1) - score_node(clean, 1) * 0.5) < 1e-9


def test_staleness_caps_at_one():
    """frequency > shown → staleness must not exceed 1.0."""
    e = _entry(a=3, b=3, last_turn=1, shown=2)
    # frequency=6, shown=2 → ratio=3, capped to 1.0
    clean = _entry(a=3, b=3, last_turn=1, shown=0)
    assert score_node(e, 1) == score_node(clean, 1)


def test_staleness_never_shown_no_penalty():
    """Node never injected (shown=0) receives no staleness penalty."""
    e     = _entry(a=1, last_turn=1, shown=0)
    e_ref = _entry(a=1, last_turn=1, shown=1)  # shown once, matched once → ratio=1
    # Both should get the same score since staleness=1.0 in both cases
    assert score_node(e, 1) == score_node(e_ref, 1)


def test_pure_loop_collapses():
    """Node shown 10 times with only 1 independent match → near-zero score."""
    loop_node  = _entry(a=1, last_turn=1, shown=10)
    clean_node = _entry(a=1, last_turn=1, shown=0)
    assert score_node(loop_node, 1) < score_node(clean_node, 1) * 0.2


# ---------------------------------------------------------------------------
# min_score_for_turn — focus narrowing
# ---------------------------------------------------------------------------

def test_turn_1_is_zero():
    """Turn 1: threshold is 0 — accept everything."""
    assert min_score_for_turn(1) == 0.0


def test_threshold_increases_monotonically():
    scores = [min_score_for_turn(t) for t in range(1, 20)]
    for a, b in zip(scores, scores[1:]):
        assert b >= a, f"threshold not monotone: turn {scores.index(a)+1}={a}, next={b}"


def test_threshold_asymptotes_below_half():
    """Threshold never reaches 0.4 (asymptote only), and stays < 0.4."""
    for t in [100, 1000, 10000]:
        assert min_score_for_turn(t) < 0.4


def test_threshold_near_limit():
    """At high turn counts, threshold is very close to 0.4."""
    assert min_score_for_turn(1000) > 0.399


# ---------------------------------------------------------------------------
# State persistence — _load_state / _save_state
# ---------------------------------------------------------------------------

def test_state_round_trip(tmp_path, monkeypatch):
    """Write and read back session state including new shown_count fields."""
    monkeypatch.setattr(_mod, "SEEN_DIR", tmp_path)

    session_id = "test-session-abc123"
    state = {
        "turn": 5,
        "nodes": {
            "node1": {"a_count": 2, "b_count": 1, "last_turn": 3,
                      "shown_count": 4, "last_shown": 3},
            "node2": {"a_count": 0, "b_count": 3, "last_turn": 5,
                      "shown_count": 2, "last_shown": 5},
        },
    }
    _save_state(session_id, state)
    loaded = _load_state(session_id)

    assert loaded["turn"] == 5
    assert loaded["nodes"]["node1"]["shown_count"] == 4
    assert loaded["nodes"]["node2"]["last_shown"] == 5


def test_load_missing_state_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "SEEN_DIR", tmp_path)
    state = _load_state("nonexistent-session")
    assert state == {"nodes": {}, "turn": 0}


def test_load_corrupt_state_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "SEEN_DIR", tmp_path)
    session_id = "corrupt-session"
    seen_file  = _seen_file(session_id)
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text("not json {{{{")
    state = _load_state(session_id)
    assert state == {"nodes": {}, "turn": 0}


# ---------------------------------------------------------------------------
# Integration: main() end-to-end via subprocess
#
# We mock the three external dependencies that would require Ollama/DB:
#   - autoground_query.query  → patched to return controlled node lists
#   - clean_and_extract_keywords → returns prompt + static keywords
#   - _query_session_chain → returns []
#
# The test script injects the mocks at import time using a wrapper approach:
# we write a small Python driver that monkey-patches then calls main().
# ---------------------------------------------------------------------------

_DRIVER_TMPL = """
import json, sys, types, importlib.util, tempfile, os
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT = {script!r}
SEEN_DIR = {seen_dir!r}
NODES_A  = {nodes_a}
NODES_B  = {nodes_b}

spec = importlib.util.spec_from_file_location("prompt_ground", SCRIPT)
mod  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.SEEN_DIR = Path(SEEN_DIR)

def _fake_clean_and_keywords(text):
    return text, ["grounding", "session", "substrate", "keyword"]

def _fake_extract_keywords(text):
    return ["session", "prior", "work"]

def _fake_chain(cwd, limit=3):
    return []

def _fake_query(keywords, top_k=10, db_path=None):
    pool = NODES_A if "grounding" in (keywords or []) else NODES_B
    return list(pool)

mod.clean_and_extract_keywords = _fake_clean_and_keywords
mod.extract_keywords            = _fake_extract_keywords
mod._query_session_chain        = _fake_chain

import autoground_query
autoground_query.query = _fake_query
sys.modules["autoground_query"] = autoground_query

payload = {payload}
sys.stdin  = __import__("io").StringIO(json.dumps(payload))
buf = __import__("io").StringIO()
sys.stdout = buf
try:
    mod.main()
except SystemExit:
    pass
out = buf.getvalue()
print(out, file=sys.__stdout__)
"""


def _run_main(payload: dict, nodes_a: list, nodes_b: list,
              seen_dir: Path) -> dict:
    """Run main() in a subprocess with mocked dependencies."""
    driver = _DRIVER_TMPL.format(
        script=str(_SCRIPT),
        seen_dir=str(seen_dir),
        nodes_a=repr(nodes_a),
        nodes_b=repr(nodes_b),
        payload=repr(payload),
    )
    result = subprocess.run(
        [sys.executable, "-c", driver],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(_mod.SUBSTRATE_DIR))},
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"driver failed:\n{result.stderr}\nstdout={result.stdout!r}")
    return json.loads(result.stdout.strip())


def _make_node(nid: str, label: str = "test node") -> dict:
    return {
        "id": nid,
        "type": "project",
        "label": label,
        "source": f"/fake/{nid}",
        "last_seen": "2026-04-10T00:00:00Z",
        "metadata": {},
    }


def test_main_returns_hook_event(tmp_path):
    """main() must always return a valid UserPromptSubmit JSON."""
    payload = {"prompt": "grounding session substrate", "session_id": "s1",
               "cwd": "/tmp/proj", "transcript_path": ""}
    nodes   = [_make_node("n1", "substrate project")]
    result  = _run_main(payload, nodes_a=nodes, nodes_b=[], seen_dir=tmp_path)
    assert result["hookEventName"] == "UserPromptSubmit"
    assert "additionalContext" in result


def test_main_context_contains_prior_work(tmp_path):
    """When nodes match, additionalContext must include prior-work block."""
    payload = {"prompt": "grounding session substrate", "session_id": "s2",
               "cwd": "/tmp/proj", "transcript_path": ""}
    nodes   = [_make_node("n1", "My substrate project")]
    result  = _run_main(payload, nodes_a=nodes, nodes_b=[], seen_dir=tmp_path)
    assert "Autoground Context" in result["additionalContext"]


def test_main_shown_count_persists(tmp_path):
    """
    Run main() twice with the same session_id.
    After the first run, shown_count for the injected node should be 1.
    After the second run, it should be 2 (and staleness penalty kicks in).
    Both runs should still return nodes (staleness = 0.5 at 2 shown / 2 freq).
    """
    payload = {"prompt": "grounding session substrate", "session_id": "s3",
               "cwd": "/tmp/proj", "transcript_path": ""}
    node    = _make_node("persistent-node")

    _run_main(payload, nodes_a=[node], nodes_b=[], seen_dir=tmp_path)
    _run_main(payload, nodes_a=[node], nodes_b=[], seen_dir=tmp_path)

    # Read state file directly
    import re
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", "s3")[:32]
    state_file = tmp_path / f"{safe}.json"
    assert state_file.exists(), "state file not written"
    state = json.loads(state_file.read_text())

    assert state["turn"] == 2
    nid_state = state["nodes"].get("persistent-node", {})
    assert nid_state.get("shown_count", 0) == 2
    assert nid_state.get("a_count", 0) == 2


def test_main_empty_prompt_returns_empty_context(tmp_path):
    """Empty prompt must not crash; returns empty additionalContext."""
    payload = {"prompt": "", "session_id": "s4",
               "cwd": "/tmp/proj", "transcript_path": ""}
    result  = _run_main(payload, nodes_a=[], nodes_b=[], seen_dir=tmp_path)
    assert result["hookEventName"] == "UserPromptSubmit"
    assert result["additionalContext"] == ""


# ---------------------------------------------------------------------------
# Run with pytest or directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
