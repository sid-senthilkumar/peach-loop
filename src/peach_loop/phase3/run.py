"""Phase 3 dispatch — executes the sub-action chosen by human at CP2.

Valid sub-actions: refactor | writeup | both | done
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from peach_loop.config import Config, resolve_path
from peach_loop.ops.logger import get_logger, setup_logging
from peach_loop.ops.state import RunState, save_state
from peach_loop.ops.digest import generate_digest

log = get_logger("phase3.run")

VALID_ACTIONS = {"refactor", "writeup", "both", "done"}


def run_phase3(
    action: str,
    base_config: Config,
    state: RunState,
    state_path: Path,
    pain_points: list[str] | None = None,
) -> RunState:
    """Dispatch Phase 3 based on human-chosen action.

    phase3_action must be one of: refactor | writeup | both | done
    pain_points: required for 'refactor' and 'both'; human provides at CP2.
    """
    from peach_loop.phase3.actions import do_refactor, do_writeup, do_done

    log_dir = resolve_path(base_config, "logs")
    setup_logging(log_dir / "events", level=getattr(getattr(base_config, "logging", base_config), "level", "INFO"))

    action = action.strip().lower()
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid Phase 3 action '{action}'.  Must be one of: {VALID_ACTIONS}")

    state.current_phase = 3
    state.phase_status = "running"
    state.phase_start_time = datetime.now(timezone.utc).isoformat()
    state.phase3_action = action
    save_state(state, state_path)

    output_dir = resolve_path(base_config, "phase3_report")
    digest_dir = resolve_path(base_config, "digests")

    phase2_report = Path(state.phase2_report_path) if state.phase2_report_path else Path("reports/phase2/phase2_comparison.md")

    log.info(f"Phase 3: action = {action}")

    if action == "done":
        summary_path = do_done(state, output_dir)
        state.phase3_report_path = str(summary_path)

    elif action == "refactor":
        if not pain_points:
            log.warning("No pain_points provided for refactor — proceeding with empty list")
            pain_points = []
        report_path = do_refactor(pain_points, base_config, state, state_path, output_dir)
        state.phase3_report_path = str(report_path)

    elif action == "writeup":
        note_path = do_writeup(phase2_report, base_config, state, output_dir)
        state.phase3_report_path = str(note_path)

    elif action == "both":
        if not pain_points:
            pain_points = []
        # Refactor first
        refactor_path = do_refactor(pain_points, base_config, state, state_path, output_dir / "refactor")
        # Then writeup using new output
        note_path = do_writeup(phase2_report, base_config, state, output_dir / "writeup")
        state.phase3_report_path = str(note_path)

    state.phase_status = "complete"
    save_state(state, state_path)

    # CP3: notify (no halt needed)
    _write_cp3_notification(state, output_dir)

    # Final digest
    generate_digest(state, base_config, digest_dir, extra_context={
        "last_24h_summary": f"Phase 3 complete. Action: {action}.",
        "forecast": "Project complete. No further autonomous actions.",
    })
    save_state(state, state_path)

    log.info("Phase 3 complete — project done.")
    return state


def _write_cp3_notification(state: RunState, output_dir: Path) -> None:
    """Write CP3 notification file (per AGENTS.md §7: notify human, no halt)."""
    notif = output_dir.parent.parent / "CP3_COMPLETE.md"
    with open(notif, "w") as f:
        f.write("# CP3 — Phase 3 Complete\n\n")
        f.write(f"**Time:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"**Action:** {state.phase3_action}\n\n")
        f.write(f"**Report:** `{state.phase3_report_path}`\n\n")
        f.write("The project is complete.  Review `reports/` for all outputs.\n")
    log.info(f"CP3 notification written: {notif}")
