"""Run-state persistence.

The state file is the single source of truth for where the autonomous run is.
It is written atomically (write-to-tmp then rename) so a mid-write crash doesn't
corrupt it.

Per AGENTS.md §1.3: disk is the source of truth.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class RunState:
    # Phase tracking
    current_phase: int = 0         # 0 = not started, 1/2/3
    phase_status: str = "not_started"  # not_started | running | complete | cap_hit | waiting

    # Timing
    launch_time: Optional[str] = None        # ISO-8601 UTC
    phase_start_time: Optional[str] = None   # ISO-8601 UTC

    # Checkpoint resume
    checkpoint_path: Optional[str] = None    # path to latest saved checkpoint
    consecutive_resume_failures: int = 0

    # CP responses
    cp1_response: Optional[str] = None   # proceed-default-sweep | proceed-with-override | abort
    cp2_response: Optional[str] = None   # refactor | writeup | both | done
    cp1_sweep_override: Optional[dict] = None   # filled when cp1_response = proceed-with-override

    # Pending human questions (non-blocking, reviewed at checkpoints)
    pending_decisions: list[dict] = field(default_factory=list)

    # Event counters
    tier1_events: list[dict] = field(default_factory=list)
    tier2_events: list[dict] = field(default_factory=list)

    # Digest schedule
    last_digest_date: Optional[str] = None  # YYYY-MM-DD of last generated digest

    # Phase 1 outputs (filled when Phase 1 completes)
    phase1_n_archetypes: Optional[int] = None
    phase1_archetype_r2: Optional[float] = None
    phase1_report_path: Optional[str] = None

    # Phase 2 outputs
    phase2_report_path: Optional[str] = None

    # Phase 3 outputs
    phase3_action: Optional[str] = None
    phase3_report_path: Optional[str] = None

    # Arbitrary metadata for inter-phase communication
    metadata: dict = field(default_factory=dict)


def load_state(state_path: str | Path) -> RunState:
    """Load RunState from JSON file, or return a fresh state if file doesn't exist."""
    path = Path(state_path)
    if not path.exists():
        return RunState()
    with open(path) as f:
        data = json.load(f)
    # Build dataclass from dict, tolerating unknown keys
    known_fields = {f.name for f in RunState.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return RunState(**filtered)


def save_state(state: RunState, state_path: str | Path) -> None:
    """Persist RunState to JSON, atomically (tmp → rename)."""
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(asdict(state), f, indent=2, default=str)
    tmp.rename(path)


def record_tier1_event(
    state: RunState,
    condition: str,
    message: str,
    extra: dict | None = None,
) -> None:
    state.tier1_events.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "condition": condition,
        "message": message,
        **(extra or {}),
    })


def record_tier2_event(
    state: RunState,
    protocol: str,
    message: str,
    extra: dict | None = None,
) -> None:
    state.tier2_events.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol,
        "message": message,
        **(extra or {}),
    })


def add_pending_decision(
    state: RunState,
    question: str,
    context: str,
    default_action: str,
) -> None:
    """Log a non-blocking question for human review at the next checkpoint."""
    state.pending_decisions.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "context": context,
        "default_action": default_action,
    })


def phase_elapsed_seconds(state: RunState) -> float:
    """Seconds since current phase started (0 if not started)."""
    if state.phase_start_time is None:
        return 0.0
    start = datetime.fromisoformat(state.phase_start_time)
    now = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (now - start).total_seconds()


def total_elapsed_seconds(state: RunState) -> float:
    """Seconds since launch (0 if not launched)."""
    if state.launch_time is None:
        return 0.0
    start = datetime.fromisoformat(state.launch_time)
    now = datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (now - start).total_seconds()
