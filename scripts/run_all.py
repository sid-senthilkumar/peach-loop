"""Main autonomous run orchestrator.

Executes Phases 1 → CP1 halt → Phase 2 → CP2 halt → Phase 3.

Checkpoint halt-and-wait protocol (AGENTS.md §7):
  1. Write checkpoints/CPn_WAITING.md with instructions for the human.
  2. Poll checkpoints/CPn_RESPONSE.txt every 60 s.
  3. Parse the response and continue.

Usage:
    python scripts/run_all.py [--config configs/base.yaml] [--resume]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is importable when run directly
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from peach_loop.config import load_config, resolve_path
from peach_loop.ops.logger import get_logger, setup_logging
from peach_loop.ops.state import RunState, load_state, save_state

log = get_logger("run_all")


# ── Checkpoint halt-and-wait ─────────────────────────────────────────────────

def wait_for_cp_response(
    cp_name: str,
    valid_responses: list[str],
    cp_report_path: Path,
    checkpoints_dir: Path,
    poll_interval_sec: int = 60,
) -> str:
    """Write a WAITING file, then block until a RESPONSE file appears.

    Returns the parsed response string.
    """
    waiting_path = checkpoints_dir / f"{cp_name}_WAITING.md"
    response_path = checkpoints_dir / f"{cp_name}_RESPONSE.txt"

    # Remove any stale response from a previous run
    if response_path.exists():
        response_path.unlink()

    # Write instructions for the human
    with open(waiting_path, "w") as f:
        f.write(f"# {cp_name} — Waiting for Human Input\n\n")
        f.write(f"**Time:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"**Report:** `{cp_report_path}`\n\n")
        f.write("## What to do\n\n")
        f.write(f"Review the report above, then create the file:\n\n")
        f.write(f"```\n{response_path}\n```\n\n")
        f.write(f"containing exactly one of these responses (plain text, no quotes):\n\n")
        for r in valid_responses:
            f.write(f"    {r}\n")
        f.write("\nThe agent will resume within 60 seconds of finding the file.\n")

    log.info(f"{cp_name}: Halted — waiting for human response at {response_path}")
    print(f"\n{'='*60}")
    print(f"  {cp_name} CHECKPOINT — WAITING FOR HUMAN INPUT")
    print(f"  Report: {cp_report_path}")
    print(f"  Write response to: {response_path}")
    print(f"  Valid responses: {valid_responses}")
    print(f"{'='*60}\n")

    while True:
        if response_path.exists():
            raw = response_path.read_text().strip().lower()
            # Accept response with or without optional suffix (e.g. "proceed-with-override n_archetypes=7")
            base_response = raw.split()[0] if raw else ""
            if base_response in valid_responses:
                log.info(f"{cp_name}: Received response: '{raw}'")
                return raw
            else:
                log.warning(
                    f"{cp_name}: Response '{raw}' not in {valid_responses} — waiting again"
                )
        time.sleep(poll_interval_sec)


def build_cp1_report(state: RunState, config, checkpoints_dir: Path, report_dir: Path) -> Path:
    """Compile the CP1 package report."""
    report_path = checkpoints_dir / "CP1_report.md"
    phase1_report = Path(state.phase1_report_path) if state.phase1_report_path else None

    lines = [
        "# Checkpoint 1 Report — Phase 1 Complete",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## §3.5 Acceptance Criteria",
        "",
        f"| Criterion | Value | Threshold | Status |",
        f"|-----------|-------|-----------|--------|",
    ]

    r2 = state.phase1_archetype_r2
    acceptance_cfg = getattr(config, "acceptance", None)
    r2_min = float(getattr(acceptance_cfg, "archetype_r2_min", 0.7)) if acceptance_cfg else 0.7
    lines.append(f"| Archetype R² | {r2:.4f if r2 else 'N/A'} | ≥ {r2_min} | {'PASS' if r2 and r2 >= r2_min else 'FAIL/N/A'} |")
    lines.append(f"| Loss monotone | See Phase 1 report | decreasing | — |")
    lines.append(f"| Resume test | Run: make test-resume | — | — |")
    lines.append(f"| Daily digest | See reports/digests/ | exists | — |")

    lines += [
        "",
        "## Phase 1 Report",
        "",
        f"See: `{phase1_report}`",
        "",
        "## Tier-2 Events During Phase 1",
        "",
    ]
    if state.tier2_events:
        for e in state.tier2_events:
            lines.append(f"- [{e.get('protocol')}] {e.get('message')}")
    else:
        lines.append("_None._")

    lines += [
        "",
        "## Pending Decisions",
        "",
    ]
    if state.pending_decisions:
        for d in state.pending_decisions:
            lines.append(f"- **{d.get('question')}** (default: {d.get('default_action')})")
    else:
        lines.append("_None._")

    lines += [
        "",
        "## Digests",
        "",
        "See `reports/digests/` for all daily digests generated during Phase 1.",
        "",
        "## Phase 2 Options",
        "",
        "Default sweep: preprocessing variants (AGENTS.md §4.1).",
        "Override options: `proceed-with-override n_archetypes` / `proceed-with-override latent_dim` / `proceed-with-override dataset`",
        "",
    ]

    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return report_path


def build_cp2_report(state: RunState, config, checkpoints_dir: Path) -> Path:
    """Compile the CP2 package report."""
    report_path = checkpoints_dir / "CP2_report.md"
    phase2_report = Path(state.phase2_report_path) if state.phase2_report_path else None

    lines = [
        "# Checkpoint 2 Report — Phase 2 Complete",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## §4.4 Acceptance Criteria",
        "",
        "| Criterion | Status |",
        "|-----------|--------|",
        f"| All variants attempted | See comparison report |",
        f"| Comparison report exists | {'✓' if phase2_report and phase2_report.exists() else '✗'} |",
        f"| Daily digest continued | See reports/digests/ |",
        "",
        "## Comparison Report",
        "",
        f"See: `{phase2_report}`",
        "",
        "## Key Question",
        "",
        "Does archetype identity survive preprocessing changes?",
        "See the correspondence and stability sections in the comparison report.",
        "",
        "## Phase 3 Options",
        "",
        "Reply with one of:",
        "- `refactor` — provide pain points; agent re-runs Phase 1 to verify",
        "- `writeup` — agent produces ~2000-word technical note from Phase 2 results",
        "- `both` — refactor then writeup",
        "- `done` — final summary only, project complete",
        "",
    ]
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return report_path


# ── Main orchestration ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Autonomous peach-loop run")
    parser.add_argument("--config", default="configs/base.yaml", help="Base config path")
    parser.add_argument("--phase1-config", default="configs/phase1.yaml")
    parser.add_argument("--sweep-config", default="configs/phase2/sweep.yaml")
    parser.add_argument("--resume", action="store_true", help="Resume from existing state")
    args = parser.parse_args()

    base_config = load_config(args.config, args.phase1_config)
    sweep_config = load_config(args.config, args.sweep_config)

    log_dir = resolve_path(base_config, "logs")
    setup_logging(log_dir / "events", level=getattr(getattr(base_config, "logging", base_config), "level", "INFO"))

    state_path = _REPO_ROOT / base_config.paths.state_file
    checkpoints_dir = resolve_path(base_config, "checkpoints")
    poll_interval = int(getattr(getattr(base_config, "checkpoint_protocol", base_config), "poll_interval_seconds", 60))

    # Load or create state
    if args.resume and state_path.exists():
        state = load_state(state_path)
        log.info(f"Resuming: phase={state.current_phase}, status={state.phase_status}")
    else:
        state = RunState()
        state.launch_time = datetime.now(timezone.utc).isoformat()
        save_state(state, state_path)
        log.info("Starting fresh run")

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    if state.current_phase <= 1 and state.phase_status not in ("waiting",):
        log.info("=== PHASE 1 START ===")
        from peach_loop.phase1.run import run_phase1
        state = run_phase1(base_config, state, state_path)
        save_state(state, state_path)
        log.info("=== PHASE 1 DONE ===")

    # ── CP1 ───────────────────────────────────────────────────────────────────
    if state.current_phase == 1 and state.cp1_response is None:
        report_dir = resolve_path(base_config, "phase1_report")
        cp1_report = build_cp1_report(state, base_config, checkpoints_dir, report_dir)
        state.phase_status = "waiting"
        save_state(state, state_path)

        response = wait_for_cp_response(
            cp_name="CP1",
            valid_responses=["proceed-default-sweep", "proceed-with-override", "abort"],
            cp_report_path=cp1_report,
            checkpoints_dir=checkpoints_dir,
            poll_interval_sec=poll_interval,
        )
        state.cp1_response = response

        if response.startswith("abort"):
            log.info("CP1: Abort requested — stopping.")
            state.phase_status = "aborted"
            save_state(state, state_path)
            sys.exit(0)

        if response.startswith("proceed-with-override"):
            # Parse: "proceed-with-override n_archetypes=7" or "proceed-with-override latent_dim"
            parts = response.split(None, 1)
            override_spec = parts[1] if len(parts) > 1 else ""
            state.cp1_sweep_override = {"spec": override_spec}
            log.info(f"CP1: Override requested: {override_spec}")

        save_state(state, state_path)

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    if state.current_phase <= 2 and state.cp1_response not in (None,) and state.cp2_response is None:
        log.info("=== PHASE 2 START ===")
        from peach_loop.phase2.run import run_phase2

        n_archetypes = state.phase1_n_archetypes or 5
        state = run_phase2(base_config, sweep_config, state, state_path, n_archetypes)
        save_state(state, state_path)
        log.info("=== PHASE 2 DONE ===")

    # ── CP2 ───────────────────────────────────────────────────────────────────
    if state.current_phase == 2 and state.cp2_response is None:
        cp2_report = build_cp2_report(state, base_config, checkpoints_dir)
        state.phase_status = "waiting"
        save_state(state, state_path)

        response = wait_for_cp_response(
            cp_name="CP2",
            valid_responses=["refactor", "writeup", "both", "done"],
            cp_report_path=cp2_report,
            checkpoints_dir=checkpoints_dir,
            poll_interval_sec=poll_interval,
        )
        state.cp2_response = response
        save_state(state, state_path)

    # ── Phase 3 ──────────────────────────────────────────────────────────────
    if state.current_phase <= 3 and state.cp2_response is not None:
        log.info(f"=== PHASE 3 START (action={state.cp2_response}) ===")
        from peach_loop.phase3.run import run_phase3

        # For refactor/both, pain points come from a file the human writes
        pain_points = _load_pain_points(checkpoints_dir)
        state = run_phase3(
            action=state.cp2_response,
            base_config=base_config,
            state=state,
            state_path=state_path,
            pain_points=pain_points,
        )
        save_state(state, state_path)
        log.info("=== PHASE 3 DONE ===")

    log.info("Autonomous run complete.")


def _load_pain_points(checkpoints_dir: Path) -> list[str]:
    """Read pain points from checkpoints/PAIN_POINTS.txt if it exists."""
    path = checkpoints_dir / "PAIN_POINTS.txt"
    if not path.exists():
        return []
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip()]
    return lines


if __name__ == "__main__":
    main()
