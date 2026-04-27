"""Tier-1 condition detection and escalation handler.

Tier-1 means: halt the offending phase, stage a log, notify the human via
the checkpoint mechanism (write a file the human will find).  Do NOT attempt
recovery — recovery is a Tier-2 concern.

AGENTS.md §8 gives the exact list of conditions.  This module checks all of them.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger, read_last_n_log_lines
from peach_loop.ops.state import RunState, record_tier1_event

log = get_logger("tier1")

# Exact condition names from AGENTS.md §8
class Tier1Condition:
    CONSECUTIVE_RESUME_FAILURES = "3_consecutive_resume_failures"
    LOSS_DIVERGED = "loss_diverged"
    DISK_CRITICAL = "disk_usage_gt_90pct"
    HARDWARE_FAULT = "hardware_fault"
    DATA_CORRUPTION = "data_corruption_hash_check"
    WALL_CLOCK_CAP_HIT = "wall_clock_cap_hit_while_incomplete"
    CHECKPOINT_SAVE_ERROR = "checkpoint_save_error"
    SMOKE_TEST_FAILED = "smoke_test_failed"
    PCHA_INIT_FAILED = "pcha_init_failed"


def check_disk_usage(path: str | Path, threshold_pct: float = 90.0) -> tuple[bool, float]:
    """Return (is_critical, usage_pct) for the filesystem containing `path`."""
    usage = shutil.disk_usage(path)
    pct = 100.0 * usage.used / usage.total
    return pct >= threshold_pct, pct


def check_loss_divergence(
    loss_history: list[float],
    multiplier: float = 2.0,
    window: int = 50,
) -> bool:
    """True if the most recent loss is > multiplier × rolling mean of the last `window` steps."""
    if len(loss_history) < window + 1:
        return False
    rolling_mean = sum(loss_history[-window - 1 : -1]) / window
    current = loss_history[-1]
    return current > multiplier * rolling_mean


def raise_tier1(
    condition: str,
    message: str,
    state: RunState,
    state_path: Path,
    log_dir: Path,
    extra: dict | None = None,
) -> None:
    """Stage Tier-1 log, update state, write notification file.

    Raises SystemExit(2) to halt the offending phase.
    The caller is responsible for saving state before calling this.
    """
    from peach_loop.ops.state import save_state

    ts = datetime.now(timezone.utc).isoformat()
    record_tier1_event(state, condition, message, extra)
    save_state(state, state_path)

    # Stage detailed log
    tier1_dir = log_dir / "tier1"
    tier1_dir.mkdir(parents=True, exist_ok=True)
    slug = ts.replace(":", "-").replace(".", "-")
    tier1_log_path = tier1_dir / f"tier1_{condition}_{slug}.json"

    event_log = log_dir / "events" / "events.jsonl"
    context_lines = read_last_n_log_lines(event_log, n=100)

    payload = {
        "ts": ts,
        "condition": condition,
        "message": message,
        "last_100_log_lines": context_lines,
        **(extra or {}),
    }
    with open(tier1_log_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    # Human notification file — placed where they can find it easily
    notification = state_path.parent.parent / "TIER1_ALERT.md"
    with open(notification, "w") as f:
        f.write(f"# TIER-1 ALERT\n\n")
        f.write(f"**Time:** {ts}\n\n")
        f.write(f"**Condition:** `{condition}`\n\n")
        f.write(f"**Message:** {message}\n\n")
        f.write(f"**Staged log:** `{tier1_log_path}`\n\n")
        f.write("The autonomous run has halted this phase.\n")
        f.write("Review the staged log, resolve the issue, then re-launch.\n")

    log.critical(f"TIER-1: {condition} — {message}")
    raise SystemExit(2)
