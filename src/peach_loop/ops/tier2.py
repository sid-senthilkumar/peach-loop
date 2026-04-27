"""Tier-2 auto-recovery protocols.

These handle failures silently: log to digest, fix the issue, continue.
Per AGENTS.md §9 — exact list of protocols.

If a Tier-2 protocol determines the situation is actually Tier-1, it raises
Tier-1 explicitly.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from peach_loop.ops.logger import get_logger
from peach_loop.ops.state import RunState, record_tier2_event

log = get_logger("tier2")


def handle_process_crash(
    state: RunState,
    state_path: Path,
    max_consecutive_failures: int = 3,
) -> bool:
    """Increment the consecutive-resume-failures counter.

    Returns True if we should attempt a resume, False if Tier-1 threshold reached.
    """
    state.consecutive_resume_failures += 1
    record_tier2_event(
        state,
        protocol="process_crash_resume",
        message=f"Attempting resume (failure #{state.consecutive_resume_failures})",
    )

    if state.consecutive_resume_failures >= max_consecutive_failures:
        log.error(f"Tier-2 escalation: {state.consecutive_resume_failures} consecutive resume failures")
        return False  # caller must raise Tier-1
    return True


def reset_resume_counter(state: RunState) -> None:
    """Call after a successful post-resume run to reset the failure counter."""
    if state.consecutive_resume_failures > 0:
        record_tier2_event(
            state,
            protocol="resume_counter_reset",
            message=f"Stable run after resume — reset counter from {state.consecutive_resume_failures} to 0",
        )
        state.consecutive_resume_failures = 0


def handle_oom(
    state: RunState,
    current_batch_size: int,
    current_grad_accum: int = 1,
) -> tuple[int, int]:
    """Halve batch size, double gradient accumulation.

    Returns (new_batch_size, new_grad_accum).
    Note: PEACH's train_archetypal does not expose a batch_size parameter in its
    public API (as of the version used here).  If PEACH uses mini-batches internally,
    we cannot control them from outside.  Record this as a pending decision.
    """
    new_batch = max(1, current_batch_size // 2)
    new_accum = current_grad_accum * 2
    record_tier2_event(
        state,
        protocol="transient_oom",
        message=f"OOM: batch {current_batch_size}→{new_batch}, grad_accum {current_grad_accum}→{new_accum}",
    )
    return new_batch, new_accum


def handle_dataloader_stall(
    state: RunState,
    stall_seconds: float,
    tier1_threshold_sec: float = 600.0,
) -> bool:
    """Return True if stall is recoverable (< threshold), False if Tier-1."""
    if stall_seconds >= tier1_threshold_sec:
        return False  # escalate to Tier-1
    record_tier2_event(
        state,
        protocol="dataloader_stall",
        message=f"Dataloader stalled {stall_seconds:.0f}s — reinitialising workers",
    )
    return True


def handle_disk_warning(
    state: RunState,
    checkpoint_dir: Path,
    usage_pct: float,
    keep: int = 5,
    tier1_threshold_pct: float = 90.0,
) -> bool:
    """Delete old checkpoints to recover disk space.

    Returns True if cleanup brought usage below threshold, False if still critical.
    """
    from peach_loop.ops.checkpoint import _cleanup_old_checkpoints
    import shutil

    record_tier2_event(
        state,
        protocol="disk_warning",
        message=f"Disk usage {usage_pct:.1f}% — cleaning old checkpoints (keeping {keep})",
    )
    _cleanup_old_checkpoints(checkpoint_dir, keep=keep)

    # Re-check
    usage = shutil.disk_usage(checkpoint_dir)
    new_pct = 100.0 * usage.used / usage.total
    if new_pct >= tier1_threshold_pct:
        log.warning(f"Disk still {new_pct:.1f}% after cleanup — escalating to Tier-1")
        return False  # caller must raise Tier-1
    log.info(f"Disk usage after cleanup: {new_pct:.1f}%")
    return True


def handle_mps_instability(state: RunState) -> str:
    """Fall back to CPU on MPS instability, per PEACH README guidance."""
    record_tier2_event(
        state,
        protocol="mps_instability",
        message="MPS backend instability detected — falling back to CPU per PEACH README",
    )
    return "cpu"


def handle_external_logging_failure(state: RunState, service_name: str) -> None:
    """Disable an external logging service, continue with local logs."""
    record_tier2_event(
        state,
        protocol="external_logging_failure",
        message=f"External logging service '{service_name}' failed — disabled, continuing with local logs",
    )


def handle_network_download_failure(
    state: RunState,
    attempt: int,
    max_attempts: int = 3,
) -> float:
    """Exponential backoff for network download failures.

    Returns seconds to sleep before retrying, or -1 if max attempts exceeded (Tier-1).
    """
    if attempt >= max_attempts:
        record_tier2_event(
            state,
            protocol="network_timeout",
            message=f"Download failed {attempt} times — escalating to Tier-1",
        )
        return -1.0
    wait = 2 ** attempt  # 2s, 4s, 8s
    record_tier2_event(
        state,
        protocol="network_timeout",
        message=f"Download failed (attempt {attempt}) — retrying in {wait}s",
    )
    return float(wait)
